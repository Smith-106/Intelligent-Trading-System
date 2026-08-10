#!/usr/bin/env python3
"""Baseline-4 **full OOS** challenger — independent contract run (not a W-wave).

Contract ID: **B4-OOS-20260810**
Contract doc: docs/research/Candidate-Baseline-4.md

Differences vs B3 (frozen):
  - entry_threshold **0.0004** / exit **0.00015** (B3 stays 0.001 / 0.0003)
  - Artifacts **only** under ``data/paper_replay/baseline4/<run_id>/``
  - Never writes ``baseline3/`` or mutates ``funding_rate.yaml``

Reuses B3 pipeline helpers (meta load, align, WFO, fee grid, adjudicate)
via importlib — logic parity, independent outputs.

    python scripts/run_baseline4_full_oos.py
    python scripts/run_baseline4_full_oos.py --run-id B4-OOS-20260810
    python scripts/run_baseline4_full_oos.py --skip-fee-grid
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from quantflow.strategy.research.contract_pin import (  # noqa: E402
    ContractPinError,
    build_window_pin,
    parse_window_ms,
    warn_if_unpinned,
)
from quantflow.strategy.validation.cost_fidelity import (  # noqa: E402
    build_funding_tca,
    summarize_measured_funding,
)

CONTRACT_ID = "B4-OOS-20260810"
OUT_ROOT = REPO_ROOT / "data" / "paper_replay" / "baseline4"
FORBIDDEN = REPO_ROOT / "data" / "paper_replay" / "baseline3"
DEFAULT_START = "2021-01-01"
DEFAULT_END = "2026-08-04"
SYMBOL = "BTC/USDT"
GATE = "nested"
TRAIN_MONTHS = 24
FWD_MONTHS = 6
MIN_FUNDING_POINTS = 24
MIN_BARS_EFFECTIVE = 500

B4_PARAMS: dict[str, Any] = {
    "entry_threshold": 0.0004,
    "exit_threshold": 0.00015,
    "oi_lookback": 3,
    "oi_change_threshold": 0.05,
}
B3_ENTRY = 0.001

FEE_GRID = [
    (0.0, 0.0),
    (0.001, 0.001),
    (0.002, 0.002),
]

VARIANTS: list[tuple[str, str, dict[str, Any] | None]] = [
    ("classic", "trend_following", None),
    ("funding_rate_b4", "funding_rate", B4_PARAMS),
]


def _load_b3():
    path = REPO_ROOT / "scripts" / "run_baseline3_challenger.py"
    spec = importlib.util.spec_from_file_location("run_baseline3_challenger", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _assert_not_b3(out_dir: Path) -> None:
    r = out_dir.resolve()
    if "baseline3" in r.parts or r == FORBIDDEN.resolve():
        raise SystemExit(f"[b4-oos] REFUSED baseline3 path: {r}")


def _sharpe(rep: dict[str, Any]) -> float:
    s = rep.get("sharpe_annualized", float("nan"))
    try:
        v = float(s)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float("nan")
    return v if v == v else float("nan")


def _pos_rate(rets: list[float]) -> float | None:
    if not rets:
        return None
    return sum(1 for r in rets if r >= 0) / len(rets)


def _wfo_segments(df: pd.DataFrame, end_ms: int) -> list[tuple[int, int, int]]:
    month_ms = 30 * 86_400_000
    train_ms = TRAIN_MONTHS * month_ms
    fwd_ms = FWD_MONTHS * month_ms
    start_ms = int(df["timestamp"].iloc[0])
    segments: list[tuple[int, int, int]] = []
    tr_end = start_ms + train_ms
    while tr_end + fwd_ms <= end_ms + 1:
        segments.append((start_ms, tr_end, tr_end + fwd_ms))
        tr_end += fwd_ms
    return segments


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--gate", default=GATE)
    ap.add_argument(
        "--require-pin",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    ap.add_argument("--skip-fee-grid", action="store_true")
    ap.add_argument(
        "--run-id",
        default=CONTRACT_ID,
        help=f"Subdir under baseline4/ (default {CONTRACT_ID})",
    )
    ap.add_argument(
        "--meta-root",
        action="append",
        default=None,
        help="Parquet root with meta_funding_rate (repeatable)",
    )
    ap.add_argument(
        "--out-root",
        default=str(OUT_ROOT.relative_to(REPO_ROOT)).replace("\\", "/"),
    )
    args = ap.parse_args(argv)

    if float(B4_PARAMS["entry_threshold"]) == float(B3_ENTRY):
        print("[b4-oos] B4 entry must differ from frozen B3 — abort", file=sys.stderr)
        return 2

    try:
        warn_if_unpinned(
            args.start, args.end, require_pin=args.require_pin, context="baseline4-oos"
        )
        start_ms, end_ms = parse_window_ms(args.start, args.end)
    except ContractPinError as exc:
        print(f"[b4-oos] pin error: {exc}", file=sys.stderr)
        return 2

    out_dir = Path(args.out_root)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir = out_dir / str(args.run_id)
    try:
        _assert_not_b3(out_dir)
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)

    b3 = _load_b3()
    meta_roots = (
        [Path(p) if Path(p).is_absolute() else REPO_ROOT / p for p in args.meta_root]
        if args.meta_root
        else [
            REPO_ROOT / "data" / "s3_verify" / "raw",
            REPO_ROOT / "data" / "parquet",
        ]
    )

    from quantflow.data.store import DataStore

    ohlcv_store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
    try:
        # Prefer query without timeframe filter when store lacks the column path
        try:
            raw = ohlcv_store.query(SYMBOL, start=start_ms, end=end_ms, timeframe="1h")
        except Exception:
            raw = ohlcv_store.query(SYMBOL, start=start_ms, end=end_ms)
    finally:
        ohlcv_store.close()

    if raw is None or raw.empty:
        print("[b4-oos] no OHLCV bars in pin window", file=sys.stderr)
        return 2

    funding, oi, meta_notes = b3._load_meta(meta_roots, SYMBOL, start_ms, end_ms)
    meta_notes = list(meta_notes)
    meta_notes.append(f"contract_id={CONTRACT_ID}")
    meta_notes.append(
        f"B4 entry_threshold={B4_PARAMS['entry_threshold']} "
        f"(B3 frozen entry={B3_ENTRY} untouched)"
    )

    data_status = "ok"
    block_reasons: list[str] = []
    if funding.empty or len(funding) < MIN_FUNDING_POINTS:
        data_status = "BLOCKED"
        block_reasons.append(
            f"funding points {len(funding)} < min {MIN_FUNDING_POINTS}"
        )

    eff_start, eff_end = start_ms, end_ms
    if not funding.empty:
        fmin = int(funding["timestamp"].min())
        fmax = int(funding["timestamp"].max())
        # Guard absurd future timestamps in sparse modern dumps
        eff_start = max(start_ms, fmin)
        eff_end = min(end_ms, fmax)
        if eff_end < eff_start:
            # funding entirely outside pin — BLOCKED
            data_status = "BLOCKED"
            block_reasons.append("funding span outside contract pin window")
        elif eff_start > start_ms or eff_end < end_ms:
            if data_status != "BLOCKED":
                data_status = "NARROWED"
            meta_notes.append(
                f"effective window narrowed to funding span "
                f"{pd.to_datetime(eff_start, unit='ms', utc=True)}→"
                f"{pd.to_datetime(eff_end, unit='ms', utc=True)}"
            )

    df = raw[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(
        drop=True
    )
    if data_status != "BLOCKED":
        df = df[(df["timestamp"] >= eff_start) & (df["timestamp"] <= eff_end)].reset_index(
            drop=True
        )
    if len(df) < MIN_BARS_EFFECTIVE and data_status != "BLOCKED":
        data_status = "BLOCKED"
        block_reasons.append(f"effective bars {len(df)} < {MIN_BARS_EFFECTIVE}")

    if data_status == "BLOCKED":
        blocked = {
            "contract_id": CONTRACT_ID,
            "status": "BLOCKED",
            "reasons": block_reasons,
            "meta_notes": meta_notes,
            "funding_points": int(len(funding)),
            "oi_points": int(len(oi)),
            "contract_window": {"start": args.start, "end": args.end},
            "b4_params": B4_PARAMS,
            "at": datetime.now(UTC).isoformat(),
        }
        (out_dir / "adjudication.json").write_text(
            json.dumps(
                {
                    "contract_id": CONTRACT_ID,
                    "verdict": "BLOCKED",
                    "upgrade": False,
                    "keep_baseline0": True,
                    "reason": "; ".join(block_reasons),
                    "data_status": "BLOCKED",
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        (out_dir / "run_meta.json").write_text(
            json.dumps(blocked, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        for name in ("funding_wfo.json", "fee_slip_grid.json", "funding_tca.json"):
            if not (out_dir / name).exists():
                (out_dir / name).write_text("{}\n", encoding="utf-8")
        print(f"[b4-oos] BLOCKED: {block_reasons} → {out_dir}", file=sys.stderr)
        return 3

    df = b3.align_meta_to_bars(df, funding, oi)
    pin = build_window_pin(
        start=args.start,
        end=args.end,
        frames={SYMBOL: df[["timestamp", "open", "high", "low", "close", "volume"]]},
        timeframe="1h",
        require_pin=args.require_pin,
    )
    df = df.copy()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    segments = _wfo_segments(df, int(df["timestamp"].iloc[-1]))
    if len(segments) < 1:
        meta_notes.append("WFO 24m/6m produced 0 segments — using 50/50 single OOS fold")
        mid = int(df["timestamp"].iloc[len(df) // 2])
        segments = [
            (int(df["timestamp"].iloc[0]), mid, int(df["timestamp"].iloc[-1]) + 1)
        ]

    funding_max_abs = (
        float(funding["funding_rate"].abs().max()) if not funding.empty else 0.0
    )
    print(
        f"[b4-oos] contract={CONTRACT_ID} status={data_status} bars={len(df)} "
        f"funding={len(funding)} max|rate|={funding_max_abs:.6g} "
        f"oi={len(oi)} segments={len(segments)}"
    )
    for n in meta_notes:
        print(f"  note: {n}")

    rows: list[dict[str, Any]] = []
    for label, strategy, params in VARIANTS:
        print(f"\n=== {label} ({strategy}) ===")
        feed = strategy == "funding_rate"
        full = asyncio.run(
            b3._eval(
                strategy,
                params,
                df.drop(columns="dt"),
                taker_fee=0.001,
                slippage=0.001,
                gate=args.gate,
                feed_meta=feed,
            )
        )
        print(
            f"  full@0.1%: ret={full.get('return_pct', float('nan'))} "
            f"sh={full.get('sharpe_annualized', float('nan'))} "
            f"dd={full.get('max_drawdown_pct', float('nan'))} "
            f"orders={full.get('orders', 0)}"
        )

        oos_rets: list[float] = []
        oos_sharpes: list[float] = []
        oos_orders = 0.0
        for i, (_s, tr_end, fwd_end) in enumerate(segments):
            fwd = df[
                (df["dt"] >= pd.to_datetime(tr_end, unit="ms", utc=True))
                & (df["dt"] < pd.to_datetime(fwd_end, unit="ms", utc=True))
            ].drop(columns="dt")
            if len(fwd) < 50:
                continue
            oos = asyncio.run(
                b3._eval(
                    strategy,
                    params,
                    fwd,
                    taker_fee=0.001,
                    slippage=0.001,
                    gate=args.gate,
                    feed_meta=feed,
                )
            )
            oos_rets.append(float(oos.get("return_pct", 0.0)))
            sh = _sharpe(oos)
            oos_sharpes.append(sh if sh == sh else -10.0)
            oos_orders += float(oos.get("orders", 0.0))
            print(
                f"  seg{i + 1}/{len(segments)} OOS {oos_rets[-1]:+.2f}% "
                f"sh={oos_sharpes[-1]:.3f} orders={oos.get('orders', 0)}"
            )

        rows.append(
            {
                "label": label,
                "strategy": strategy,
                "params": params,
                "full_return_pct": full.get("return_pct"),
                "full_max_dd_pct": full.get("max_drawdown_pct"),
                "full_sharpe": full.get("sharpe_annualized"),
                "full_orders": full.get("orders"),
                "wfo_segments": len(oos_rets),
                "wfo_oos_sum_pct": sum(oos_rets) if oos_rets else None,
                "wfo_oos_mean_pct": (sum(oos_rets) / len(oos_rets)) if oos_rets else None,
                "wfo_oos_mean_sharpe": (sum(oos_sharpes) / len(oos_sharpes))
                if oos_sharpes
                else None,
                "wfo_pos_rate": _pos_rate(oos_rets),
                "wfo_orders": oos_orders,
            }
        )

    fee_rows: list[dict[str, Any]] = []
    if not args.skip_fee_grid:
        print("\n=== fee×slip grid ===")
        bars = df.drop(columns="dt")
        for label, strategy, params in VARIANTS:
            feed = strategy == "funding_rate"
            for fee, slip in FEE_GRID:
                rep = asyncio.run(
                    b3._eval(
                        strategy,
                        params,
                        bars,
                        taker_fee=fee,
                        slippage=slip,
                        gate=args.gate,
                        feed_meta=feed,
                    )
                )
                cell = {
                    "label": label,
                    "strategy": strategy,
                    "taker_fee": fee,
                    "slippage": slip,
                    "return_pct": rep.get("return_pct"),
                    "sharpe": rep.get("sharpe_annualized"),
                    "max_drawdown_pct": rep.get("max_drawdown_pct"),
                    "orders": rep.get("orders"),
                }
                fee_rows.append(cell)
                print(
                    f"  {label} fee={fee} slip={slip} "
                    f"ret={cell['return_pct']} sh={cell['sharpe']} orders={cell['orders']}"
                )

    adjudicate = b3._load_adjudicate()
    adj = adjudicate(rows, fee_rows)
    # Force B4 envelope — never claim UPGRADE to rewrite B0 without human
    adj["contract_id"] = CONTRACT_ID
    adj["baseline"] = "B4"
    adj["data_status"] = data_status
    adj["meta_notes"] = meta_notes
    adj["b4_params"] = B4_PARAMS
    adj["b3_frozen_entry_threshold"] = B3_ENTRY
    adj["funding_max_abs"] = funding_max_abs
    # Map B1-style keys → B4 keep semantics
    upgrade = bool(adj.get("upgrade_to_baseline1") or adj.get("upgrade"))
    # Extra hard gate: if challenger has 0 full orders → KEEP
    b4_row = next((r for r in rows if r["label"] == "funding_rate_b4"), None)
    if b4_row and float(b4_row.get("full_orders") or 0) <= 0:
        upgrade = False
        adj["reason"] = (
            (adj.get("reason") or "")
            + " | B4 full_orders=0 under thr=0.0004 → KEEP_BASELINE_0"
        ).strip(" |")
    if data_status == "NARROWED":
        adj["reason"] = (
            (adj.get("reason") or "")
            + " | effective window narrowed to meta funding coverage"
        ).strip(" |")
    adj["upgrade"] = False if not upgrade else upgrade
    adj["keep_baseline0"] = not bool(adj["upgrade"])
    adj["verdict"] = "UPGRADE" if adj["upgrade"] else "KEEP_BASELINE_0"
    # Research OS: do not auto-promote even if adjudicate said upgrade
    if adj["upgrade"]:
        adj["promotion_eligible"] = False
        adj["human_required"] = True
        adj["note_auto"] = (
            "Adjudicate suggested upgrade; contract still requires human seal "
            "and must not overwrite B0 PAPER-GO automatically"
        )

    rates = (
        [float(x) for x in funding["funding_rate"].tolist()] if not funding.empty else []
    )
    measured = (
        summarize_measured_funding(
            rates,
            symbol=SYMBOL,
            start_ms=int(funding["timestamp"].min()) if not funding.empty else None,
            end_ms=int(funding["timestamp"].max()) if not funding.empty else None,
        )
        if rates
        else None
    )
    tca = (
        build_funding_tca(mode="hybrid", measured=measured)
        if measured
        else build_funding_tca(mode="assumption")
    )

    run_meta = {
        "contract_id": CONTRACT_ID,
        "contract_doc": "docs/research/Candidate-Baseline-4.md",
        "status": data_status,
        "symbol": SYMBOL,
        "gate": args.gate,
        "execution_path": "paper_replay",
        "params": B4_PARAMS,
        "b3_frozen_entry_threshold": B3_ENTRY,
        "contract_window": {"start": args.start, "end": args.end},
        "effective_window_ms": {"start": eff_start, "end": eff_end},
        "bars": len(df),
        "funding_points": len(funding),
        "funding_max_abs": funding_max_abs,
        "oi_points": len(oi),
        "wfo_segments": len(segments),
        "data_fingerprint": pin.data_fingerprint,
        "meta_notes": meta_notes,
        "promotion_eligible": False,
        "ran_at": datetime.now(UTC).isoformat(),
        "artifacts_root": str(out_dir).replace("\\", "/"),
    }

    (out_dir / "funding_wfo.json").write_text(
        json.dumps({"rows": rows, "segments": len(segments)}, indent=2, default=str)
        + "\n",
        encoding="utf-8",
    )
    (out_dir / "fee_slip_grid.json").write_text(
        json.dumps({"rows": fee_rows}, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (out_dir / "funding_tca.json").write_text(
        json.dumps(tca, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (out_dir / "adjudication.json").write_text(
        json.dumps(adj, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (out_dir / "run_meta.json").write_text(
        json.dumps(run_meta, indent=2, default=str) + "\n", encoding="utf-8"
    )

    # Freeze KEEP (template materialization)
    freeze_path = REPO_ROOT / "scripts" / "freeze_baseline4_adjudication.py"
    if freeze_path.is_file():
        import scripts.freeze_baseline4_adjudication as freeze_mod

        freeze_mod.freeze(out_dir)

    print(
        f"\n[b4-oos] verdict={adj.get('verdict')} upgrade={adj.get('upgrade')} "
        f"keep_b0={adj.get('keep_baseline0')}"
    )
    print(f"[b4-oos] wrote → {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
