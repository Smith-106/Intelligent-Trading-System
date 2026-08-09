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
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    rc = 0

    if not args.skip_full:
        full_out = OUT_DIR / "multi_symbol_replay.json"
        rc = _run(
            [
                py,
                str(REPO_ROOT / "scripts" / "multi_symbol_replay.py"),
                "--symbols",
                SYMBOLS,
                "--start",
                START,
                "--end",
                END,
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
                START,
                "--end",
                END,
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

    cost_ok = False
    if not args.skip_cost_grid:
        # P0 T002: default dual report — production fee/slip grid + risk ablation.
        cost_cmd = [
            py,
            str(REPO_ROOT / "scripts" / "reframe_sensitivity_1h.py"),
            "--symbol",
            "BTC/USDT",
            "--end",
            END,
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
            print(
                f"[baseline0] cost fidelity: fee_slip_cells={len(grid)} "
                f"risk_cases={len(risk)} → {COST_REPORT}"
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

    meta = {
        "contract": "docs/research/Candidate-Baseline-0.md",
        "ran_at": datetime.now(UTC).isoformat(),
        "symbols": SYMBOLS,
        "start": START,
        "end": END,
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
        "outputs": {
            "full": "data/paper_replay/baseline0/multi_symbol_replay.json",
            "wfo": "data/paper_replay/baseline0/wfo_shared_rp.json",
            "cost_fidelity": "data/paper_replay/baseline0/cost_fidelity_report.json",
        },
        "reporting": {
            "required_for_go_narrative": [
                "fee_slip_grid (zero + production cells)",
                "risk_ablation (research_bypass vs production risk)",
            ],
            "note": "Zero-cost Sharpe alone must not drive GO (knowhow fee/slip).",
        },
    }
    meta_path = OUT_DIR / "run_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[baseline0] meta written {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
