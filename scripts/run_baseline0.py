#!/usr/bin/env python3
"""Run Candidate Baseline-0 reproduction (paper shared-book symbol RP).

Locked contract: docs/research/Candidate-Baseline-0.md

Writes:
  data/paper_replay/baseline0/multi_symbol_replay.json
  data/paper_replay/baseline0/wfo_shared_rp.json
  data/paper_replay/baseline0/run_meta.json
  data/paper_replay/baseline0/cost_fidelity_report.json   (P0 T002 dual report)

By default also runs fee×slip grid + dual risk ablation via
scripts/reframe_sensitivity_1h.py (skip with --skip-cost-grid).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Locked contract values (must match Candidate-Baseline-0.md)
SYMBOLS = "BTC/USDT,ETH/USDT,SOL/USDT"
START = "2021-01-01"
END = "2026-08-04"
GATE = "nested"
FEE = "0.001"
SLIP = "0.001"
TRAIN_MONTHS = "24"
FWD_MONTHS = "6"
REBALANCE_BARS = "48"
OUT_DIR = REPO_ROOT / "data" / "paper_replay" / "baseline0"
COST_REPORT = OUT_DIR / "cost_fidelity_report.json"


def _run(cmd: list[str]) -> int:
    print("[baseline0]", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), check=False)
    return int(proc.returncode)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skip-full", action="store_true", help="Skip multi_symbol full-window run")
    ap.add_argument("--skip-wfo", action="store_true", help="Skip WFO OOS run")
    ap.add_argument(
        "--skip-cost-grid",
        action="store_true",
        help="Skip fee×slip + dual-risk report (not recommended for GO narratives)",
    )
    ap.add_argument(
        "--cost-days",
        type=int,
        default=0,
        help="Days of 1h history for cost grid (0 = full span to contract end)",
    )
    ap.add_argument(
        "--start",
        default=START,
        help=f"Contract start (default locked {START})",
    )
    ap.add_argument(
        "--end",
        default=END,
        help=f"Contract end inclusive (default locked {END})",
    )
    ap.add_argument(
        "--require-pin",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fail if start/end missing (default: true; T011)",
    )
    args = ap.parse_args()

    from quantflow.data.store import DataStore
    from quantflow.strategy.research.contract_pin import (
        ContractPinError,
        build_window_pin,
        load_and_fingerprint_symbols,
        parse_window_ms,
        warn_if_unpinned,
    )

    try:
        warn_if_unpinned(
            args.start,
            args.end,
            require_pin=args.require_pin,
            context="run_baseline0",
        )
        start_ms, end_ms = parse_window_ms(args.start, args.end)
    except ContractPinError as exc:
        print(f"[baseline0] pin error: {exc}", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    rc = 0
    start_s, end_s = str(args.start), str(args.end)

    if not args.skip_full:
        full_out = OUT_DIR / "multi_symbol_replay.json"
        rc = _run(
            [
                py,
                str(REPO_ROOT / "scripts" / "multi_symbol_replay.py"),
                "--symbols",
                SYMBOLS,
                "--start",
                start_s,
                "--end",
                end_s,
                "--gate",
                GATE,
                "--fee",
                FEE,
                "--slip",
                SLIP,
                "--out",
                str(full_out.relative_to(REPO_ROOT)).replace("\\", "/"),
            ]
        )
        if rc != 0:
            return rc

    if not args.skip_wfo:
        wfo_out = OUT_DIR / "wfo_shared_rp.json"
        rc = _run(
            [
                py,
                str(REPO_ROOT / "scripts" / "wfo_shared_rp.py"),
                "--symbols",
                SYMBOLS,
                "--start",
                start_s,
                "--end",
                end_s,
                "--train-months",
                TRAIN_MONTHS,
                "--fwd-months",
                FWD_MONTHS,
                "--gate",
                GATE,
                "--fee",
                FEE,
                "--slip",
                SLIP,
                "--rebalance-bars",
                REBALANCE_BARS,
                "--out",
                str(wfo_out.relative_to(REPO_ROOT)).replace("\\", "/"),
            ]
        )
        if rc != 0:
            return rc

    # T014: funding/TCA block (assumption or hybrid measured) — required for GO narrative.
    funding_path = OUT_DIR / "funding_tca.json"
    funding_ok = False
    funding_block: dict | None = None
    rc_f = _run(
        [
            py,
            str(REPO_ROOT / "scripts" / "funding_tca_report.py"),
            "--symbol",
            "BTC-USDT-SWAP",
            "--out",
            str(funding_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        ]
    )
    if rc_f == 0 and funding_path.is_file():
        funding_payload = json.loads(funding_path.read_text(encoding="utf-8"))
        funding_block = funding_payload.get("funding_tca")
        funding_ok = isinstance(funding_block, dict)
        if funding_ok:
            print(
                f"[baseline0] funding_tca mode={funding_block.get('mode')} "
                f"annual_drag≈{funding_block.get('estimated_annual_drag_pct')}% "
                f"→ {funding_path}"
            )
    else:
        print(
            "[baseline0] WARN: funding_tca_report failed; GO narrative incomplete (T014)",
            flush=True,
        )

    cost_ok = False
    if not args.skip_cost_grid:
        # P0 T002: default dual report — production fee/slip grid + risk ablation.
        cost_cmd = [
            py,
            str(REPO_ROOT / "scripts" / "reframe_sensitivity_1h.py"),
            "--symbol",
            "BTC/USDT",
            "--end",
            end_s,
            "--gate",
            GATE,
            "--out",
            str(COST_REPORT.relative_to(REPO_ROOT)).replace("\\", "/"),
        ]
        if args.cost_days > 0:
            cost_cmd.extend(["--days", str(args.cost_days)])
        rc = _run(cost_cmd)
        if rc != 0:
            return rc
        cost_ok = COST_REPORT.is_file()
        if cost_ok:
            payload = json.loads(COST_REPORT.read_text(encoding="utf-8"))
            grid = payload.get("fee_slip_grid") or []
            risk = payload.get("risk_ablation") or []
            # Merge funding_tca into cost report for assert_promotion_cost_ready.
            if funding_block is not None:
                payload["funding_tca"] = funding_block
                COST_REPORT.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
                )
            print(
                f"[baseline0] cost fidelity: fee_slip_cells={len(grid)} "
                f"risk_cases={len(risk)} funding_tca={funding_ok} → {COST_REPORT}"
            )
            if not grid:
                print("[baseline0] ERROR: cost report missing fee_slip_grid", file=sys.stderr)
                return 2
    else:
        print(
            "[baseline0] WARN: --skip-cost-grid set; GO narratives without "
            "fee×slip dual report are incomplete (P0 T002)",
            flush=True,
        )

    # T011: fingerprint the locked contract window against local parquet.
    symbols_list = [s.strip() for s in SYMBOLS.split(",") if s.strip()]
    store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
    try:
        frames, _ = load_and_fingerprint_symbols(
            store,
            symbols_list,
            start_ms=start_ms,
            end_ms=end_ms,
            timeframe="1h",
        )
        pin = build_window_pin(
            start=start_s,
            end=end_s,
            frames=frames,
            timeframe="1h",
            require_pin=args.require_pin,
        )
    finally:
        store.close()

    meta = {
        "contract": "docs/research/Candidate-Baseline-0.md",
        "ran_at": datetime.now(UTC).isoformat(),
        "symbols": SYMBOLS,
        "start": start_s,
        "end": end_s,
        "start_ms": pin.start_ms,
        "end_ms": pin.end_ms,
        "timeframe": pin.timeframe,
        "data_fingerprint": pin.data_fingerprint,
        "require_pin": args.require_pin,
        "gate": GATE,
        "fee": float(FEE),
        "slip": float(SLIP),
        "train_months": int(TRAIN_MONTHS),
        "fwd_months": int(FWD_MONTHS),
        "rebalance_bars": int(REBALANCE_BARS),
        "skip_full": args.skip_full,
        "skip_wfo": args.skip_wfo,
        "skip_cost_grid": args.skip_cost_grid,
        "cost_fidelity_included": cost_ok,
        "funding_tca_included": funding_ok,
        "funding_tca": funding_block,
        "outputs": {
            "full": "data/paper_replay/baseline0/multi_symbol_replay.json",
            "wfo": "data/paper_replay/baseline0/wfo_shared_rp.json",
            "cost_fidelity": "data/paper_replay/baseline0/cost_fidelity_report.json",
            "funding_tca": "data/paper_replay/baseline0/funding_tca.json",
        },
        "reporting": {
            "required_for_go_narrative": [
                "fee_slip_grid (zero + production cells)",
                "risk_ablation (research_bypass vs production risk)",
                "data_fingerprint (T011 pin)",
                "funding_tca (assumption|measured|hybrid; T014)",
            ],
            "note": (
                "Zero-cost Sharpe alone must not drive GO (knowhow fee/slip). "
                "Re-runs must match start/end + data_fingerprint.aggregate. "
                "Funding/TCA must be cited next to fee×slip (T014 fail-closed on register)."
            ),
        },
    }
    print(
        f"[baseline0] pin window={start_s}→{end_s} ms=[{pin.start_ms},{pin.end_ms}] "
        f"fp={pin.data_fingerprint.get('aggregate')} "
        f"symbols={list((pin.data_fingerprint.get('symbols') or {}).keys())}"
    )
    meta_path = OUT_DIR / "run_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[baseline0] meta written {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
