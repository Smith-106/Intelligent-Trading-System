#!/usr/bin/env python3
"""Baseline-1 challenger pipeline: non-MA signal families vs classic (T012).

Protocol (aligned with Candidate-Baseline-0 / Wave C):
  - Window pin: 2021-01-01 → 2026-08-04 (override with --start/--end)
  - BTC 1h + nested direction gate
  - Fixed params only (no Optuna)
  - WFO OOS: train 24m / fwd 6m
  - Fee×slip grid: 0/0, 0.1%/0.1%, 0.2%/0.2% on full pin window

Writes under data/paper_replay/baseline1/:
  nonma_wfo.json, fee_slip_grid.json, adjudication.json, run_meta.json

Does **not** auto-upgrade Baseline-0. Adjudication is KEEP/REJECT/UPGRADE
per Wave-C rules; UPGRADE is rare and must be explicit.

    python scripts/run_baseline1_challenger.py
    python scripts/run_baseline1_challenger.py --skip-fee-grid
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from quantflow.common.config import AppConfig, ExecutionConfig, RiskConfig  # noqa: E402
from quantflow.strategy.research.contract_pin import (  # noqa: E402
    ContractPinError,
    build_window_pin,
    parse_window_ms,
    warn_if_unpinned,
)
from quantflow.strategy.research.paper_replay import (  # noqa: E402
    RecordingSink,
    aggregate,
    build_session,
    replay,
)

OUT_DIR = REPO_ROOT / "data" / "paper_replay" / "baseline1"
DEFAULT_START = "2021-01-01"
DEFAULT_END = "2026-08-04"
SYMBOL = "BTC/USDT"
GATE = "nested"
TRAIN_MONTHS = 24
FWD_MONTHS = 6

VARIANTS: list[tuple[str, str, dict[str, Any] | None]] = [
    ("classic", "trend_following", None),
    ("donchian", "non_ma_signal", {"signal_family": "donchian"}),
    ("volume_roc", "non_ma_signal", {"signal_family": "volume_roc"}),
    ("rsi_thrust", "non_ma_signal", {"signal_family": "rsi_thrust"}),
]

FEE_GRID = [
    (0.0, 0.0),
    (0.001, 0.001),
    (0.002, 0.002),
]


def _sharpe(rep: dict[str, Any]) -> float:
    s = rep.get("sharpe_annualized", float("nan"))
    try:
        v = float(s)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float("nan")
    return v if v == v else float("nan")


async def _eval(
    strategy: str,
    params: dict[str, Any] | None,
    bars: pd.DataFrame,
    *,
    taker_fee: float = 0.001,
    slippage: float = 0.001,
    gate: str | bool = GATE,
) -> dict[str, float]:
    cfg = AppConfig(
        execution=ExecutionConfig(
            taker_fee=taker_fee,
            maker_fee=taker_fee * 0.8,
            slippage=slippage,
            mode="paper",
        ),
        risk=RiskConfig(),
    )
    sink = RecordingSink()
    session = build_session(
        strategy,
        100_000.0,
        sink,
        config=cfg,
        params=params,
        research_risk_bypass=True,
    )
    fills: list[dict[str, object]] = []
    risk: list[dict[str, object]] = []
    curve = await replay(session, bars, SYMBOL, fills, risk, direction_gate=gate, entry_tf="1h")
    rep = aggregate(curve, fills, risk, sink.alerts, 100_000.0, entry_tf="1h")
    out: dict[str, float] = {}
    for k, v in rep.items():
        if isinstance(v, (int, float)):
            out[k] = float(v)
        elif v is None and k == "sharpe_annualized":
            out[k] = float("nan")
    return out


def _wfo_segments(df: pd.DataFrame, end_ms: int) -> list[tuple[int, int, int]]:
    month_ms = 30 * 86_400_000
    train_ms = TRAIN_MONTHS * month_ms
    step_ms = FWD_MONTHS * month_ms
    first_end = int(df["dt"].min().timestamp() * 1000) + train_ms
    segments: list[tuple[int, int, int]] = []
    t_end = first_end
    data_end = int(df["dt"].max().timestamp() * 1000)
    while t_end + step_ms <= min(end_ms, data_end + 1):
        segments.append((t_end - train_ms, t_end, t_end + step_ms))
        t_end += step_ms
    return segments


def _pos_rate(rets: list[float]) -> str:
    if not rets:
        return "0/0"
    return f"{sum(1 for r in rets if r > 0)}/{len(rets)}"


def adjudicate(rows: list[dict[str, Any]], fee_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Wave-C upgrade rule vs classic at production fee 0.1%/0.1%."""
    by_label = {r["label"]: r for r in rows}
    classic = by_label.get("classic")
    if classic is None:
        return {
            "verdict": "REJECT",
            "reason": "classic baseline row missing",
            "upgrade_to_baseline1": False,
        }

    challengers = [r for r in rows if r["label"] != "classic"]
    # Primary rank: OOS mean sharpe at default 0.1%/0.1% (WFO path uses that fee).
    ranked = sorted(
        challengers,
        key=lambda r: (
            r.get("wfo_oos_mean_sharpe")
            if r.get("wfo_oos_mean_sharpe") is not None
            and r["wfo_oos_mean_sharpe"] == r["wfo_oos_mean_sharpe"]
            else -99.0,
            r.get("wfo_oos_sum_pct") or -99.0,
        ),
        reverse=True,
    )
    best = ranked[0] if ranked else None
    c_sh = classic.get("wfo_oos_mean_sharpe") or float("nan")
    c_sum = classic.get("wfo_oos_sum_pct") or float("nan")
    c_dd = classic.get("full_max_dd_pct") or float("nan")

    checks: list[dict[str, Any]] = []
    upgrade = False
    verdict = "KEEP_BASELINE_0"
    reason = "no challenger beats classic on Wave-C upgrade rule"

    if best is not None:
        b_sh = best.get("wfo_oos_mean_sharpe")
        b_sum = best.get("wfo_oos_sum_pct")
        b_dd = best.get("full_max_dd_pct")
        b_sh_f = float(b_sh) if b_sh is not None else float("nan")
        b_sum_f = float(b_sum) if b_sum is not None else float("nan")
        b_dd_f = float(b_dd) if b_dd is not None else float("nan")

        go_sh = b_sh_f > 0 and b_sh_f == b_sh_f
        go_sum = b_sum_f >= 0 and b_sum_f == b_sum_f
        sh_ge = b_sh_f >= c_sh and b_sh_f == b_sh_f and c_sh == c_sh
        # DD: lower is better (stored as positive pct drawdown magnitude in reports)
        dd_ok = b_dd_f <= c_dd * 1.20 if (b_dd_f == b_dd_f and c_dd == c_dd and c_dd > 0) else False
        sum_ge = b_sum_f >= c_sum and b_sum_f == b_sum_f

        checks = [
            {"name": "challenger_oos_mean_sharpe_gt_0", "pass": go_sh, "value": b_sh_f},
            {"name": "challenger_oos_sum_pct_ge_0", "pass": go_sum, "value": b_sum_f},
            {
                "name": "oos_mean_sharpe_ge_classic",
                "pass": sh_ge,
                "value": b_sh_f,
                "classic": c_sh,
            },
            {
                "name": "dd_not_worse_than_classic_plus_20pct",
                "pass": dd_ok or (sum_ge and go_sh),
                "value": b_dd_f,
                "classic": c_dd,
            },
            {"name": "no_optuna", "pass": True},
        ]
        all_go = all(c["pass"] for c in checks)
        if all_go and sh_ge and go_sh:
            upgrade = True
            verdict = "UPGRADE_BASELINE_1"
            reason = (
                f"{best['label']} meets Wave-C upgrade vs classic "
                f"(OOS meanSh {b_sh_f:.3f} >= {c_sh:.3f})"
            )
        else:
            # Explicit reject of all non-classic if none upgrade
            any_positive = any((r.get("wfo_oos_mean_sharpe") or -1) > 0 for r in challengers)
            verdict = "KEEP_BASELINE_0"
            reason = (
                f"best challenger={best['label']} OOS meanSh={b_sh_f:.3f} "
                f"vs classic={c_sh:.3f}; upgrade={all_go and sh_ge}; "
                f"any_challenger_positive_oos_sh={any_positive}"
            )

    # Fee grid: production cell must not be pure zero-cost narrative
    prod_cells = [
        r
        for r in fee_rows
        if abs(float(r.get("taker_fee", -1)) - 0.001) < 1e-12
        and abs(float(r.get("slippage", -1)) - 0.001) < 1e-12
    ]
    zero_cells = [
        r
        for r in fee_rows
        if float(r.get("taker_fee", 1)) == 0.0 and float(r.get("slippage", 1)) == 0.0
    ]
    fee_note = {
        "production_cells": len(prod_cells),
        "zero_cells": len(zero_cells),
        "rule": "GO narratives must cite 0.1%/0.1% cell, not zero-cost only",
    }

    return {
        "verdict": verdict,
        "upgrade_to_baseline1": upgrade,
        "keep_baseline0": not upgrade,
        "best_challenger": best["label"] if best else None,
        "classic_oos_mean_sharpe": c_sh,
        "classic_oos_sum_pct": c_sum,
        "checks": checks,
        "reason": reason,
        "fee_slip_policy": fee_note,
        "wave_c_rule": (
            "Promote only if all GO-like OOS checks pass AND OOS mean Sharpe >= classic "
            "AND DD not worse by >20% (or return compensates); no Optuna"
        ),
    }


def main() -> int:
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
        "--out-dir",
        default=str(OUT_DIR.relative_to(REPO_ROOT)).replace("\\", "/"),
    )
    args = ap.parse_args()

    try:
        warn_if_unpinned(args.start, args.end, require_pin=args.require_pin, context="baseline1")
        start_ms, end_ms = parse_window_ms(args.start, args.end)
    except ContractPinError as exc:
        print(f"[b1] pin error: {exc}", file=sys.stderr)
        return 2

    from quantflow.data.store import DataStore

    store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
    try:
        raw = store.query(SYMBOL, start=start_ms, end=end_ms, timeframe="1h")
    finally:
        store.close()
    if raw.empty:
        print("[b1] no bars in pin window", file=sys.stderr)
        return 2

    df = raw[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    pin = build_window_pin(
        start=args.start,
        end=args.end,
        frames={SYMBOL: df},
        timeframe="1h",
        require_pin=args.require_pin,
    )
    df = df.copy()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms")
    segments = _wfo_segments(df, end_ms)
    print(
        f"[b1] pin {args.start}→{args.end} bars={len(df)} segments={len(segments)} "
        f"fp={pin.data_fingerprint.get('aggregate')} gate={args.gate}"
    )

    rows: list[dict[str, Any]] = []
    for label, strategy, params in VARIANTS:
        print(f"\n=== {label} ({strategy}) ===")
        full = asyncio.run(
            _eval(
                strategy,
                params,
                df.drop(columns="dt"),
                taker_fee=0.001,
                slippage=0.001,
                gate=args.gate,
            )
        )
        print(
            f"  full@0.1%: ret={full.get('return_pct', float('nan')):+.2f}% "
            f"sh={full.get('sharpe_annualized', float('nan'))} "
            f"dd={full.get('max_drawdown_pct', float('nan'))} orders={full.get('orders', 0)}"
        )

        oos_rets: list[float] = []
        oos_sharpes: list[float] = []
        oos_orders = 0.0
        for i, (_s, tr_end, fwd_end) in enumerate(segments):
            fwd = df[
                (df["dt"] >= pd.to_datetime(tr_end, unit="ms"))
                & (df["dt"] < pd.to_datetime(fwd_end, unit="ms"))
            ].drop(columns="dt")
            if len(fwd) < 50:
                continue
            oos = asyncio.run(
                _eval(
                    strategy,
                    params,
                    fwd,
                    taker_fee=0.001,
                    slippage=0.001,
                    gate=args.gate,
                )
            )
            oos_rets.append(float(oos.get("return_pct", 0.0)))
            sh = _sharpe(oos)
            oos_sharpes.append(sh if sh == sh else -10.0)
            oos_orders += float(oos.get("orders", 0.0))
            print(f"  seg{i + 1}/{len(segments)} OOS {oos_rets[-1]:+.2f}% sh={oos_sharpes[-1]:.3f}")

        row = {
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
            "wfo_oos_mean_sharpe": (sum(oos_sharpes) / len(oos_sharpes)) if oos_sharpes else None,
            "wfo_pos_rate": _pos_rate(oos_rets),
            "wfo_orders": oos_orders,
        }
        rows.append(row)

    fee_rows: list[dict[str, Any]] = []
    if not args.skip_fee_grid:
        # Grid on classic + best non-classic by OOS sharpe so far
        non_classic = [r for r in rows if r["label"] != "classic"]
        best_nc = (
            max(
                non_classic,
                key=lambda r: (
                    r.get("wfo_oos_mean_sharpe")
                    if r.get("wfo_oos_mean_sharpe") is not None
                    else -99
                ),
            )
            if non_classic
            else None
        )
        grid_targets = [("classic", "trend_following", None)]
        if best_nc is not None:
            grid_targets.append((best_nc["label"], best_nc["strategy"], best_nc.get("params")))
        print("\n=== fee×slip grid ===")
        bars = df.drop(columns="dt")
        for label, strategy, params in grid_targets:
            for fee, slip in FEE_GRID:
                rep = asyncio.run(
                    _eval(
                        strategy,
                        params,
                        bars,
                        taker_fee=fee,
                        slippage=slip,
                        gate=args.gate,
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
                    f"  {label} fee={fee} slip={slip} ret={cell['return_pct']} sh={cell['sharpe']}"
                )

    adj = adjudicate(rows, fee_rows)
    print(f"\n[b1] verdict={adj['verdict']} reason={adj['reason']}")

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    nonma_path = out_dir / "nonma_wfo.json"
    fee_path = out_dir / "fee_slip_grid.json"
    adj_path = out_dir / "adjudication.json"
    meta_path = out_dir / "run_meta.json"

    nonma_payload = {
        "symbol": SYMBOL,
        "entry_tf": "1h",
        "gate": args.gate,
        "window": pin.to_dict(),
        "train_months": TRAIN_MONTHS,
        "fwd_months": FWD_MONTHS,
        "note": "T012 fixed params; non-MA families vs classic; production fee on WFO",
        "rows": rows,
        "winner_by_oos_mean_sharpe": max(
            rows,
            key=lambda r: (
                r.get("wfo_oos_mean_sharpe") if r.get("wfo_oos_mean_sharpe") is not None else -99
            ),
        )["label"],
    }
    nonma_path.write_text(json.dumps(nonma_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    fee_path.write_text(
        json.dumps(
            {
                "grid": fee_rows,
                "cells": FEE_GRID,
                "note": "Full pin window; research_risk_bypass=True",
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    adj_path.write_text(json.dumps(adj, indent=2, ensure_ascii=False), encoding="utf-8")
    meta = {
        "task": "T012",
        "contract_docs": [
            "docs/research/Candidate-Baseline-0.md",
            "docs/research/Candidate-Baseline-1.md",
        ],
        "ran_at": datetime.now(UTC).isoformat(),
        "start": args.start,
        "end": args.end,
        "start_ms": pin.start_ms,
        "end_ms": pin.end_ms,
        "data_fingerprint": pin.data_fingerprint,
        "verdict": adj["verdict"],
        "upgrade_to_baseline1": adj["upgrade_to_baseline1"],
        "outputs": {
            "nonma_wfo": str(nonma_path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "fee_slip_grid": str(fee_path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "adjudication": str(adj_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        },
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[b1] wrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
