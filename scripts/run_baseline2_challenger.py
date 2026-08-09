#!/usr/bin/env python3
"""Baseline-2 complementary signal families (T013).

Complements Baseline-0 (classic trend / multi-symbol RP) and Baseline-1
(non-MA trend-ish families):

  - mean_reversion  — RSI+BB, required_regime=mean_reversion (anti-trend)
  - volatility_breakout — ATR/BB/Keltner expansion (vol-regime breakout)

Same protocol as run_baseline1_challenger.py:
  pin 2021-01-01→2026-08-04, BTC 1h nested, WFO 24m/6m, fee 0.1%/0.1%,
  fee×slip grid, no Optuna, Wave-C upgrade vs classic.

    python scripts/run_baseline2_challenger.py
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

OUT_DIR = REPO_ROOT / "data" / "paper_replay" / "baseline2"
DEFAULT_START = "2021-01-01"
DEFAULT_END = "2026-08-04"
SYMBOL = "BTC/USDT"
GATE = "nested"
TRAIN_MONTHS = 24
FWD_MONTHS = 6

VARIANTS: list[tuple[str, str, dict[str, Any] | None]] = [
    ("classic", "trend_following", None),
    ("mean_reversion", "mean_reversion", None),
    ("volatility_breakout", "volatility_breakout", None),
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
    curve = await replay(
        session, bars, SYMBOL, fills, risk, direction_gate=gate, entry_tf="1h"
    )
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


def _load_adjudicate():
    """Load Wave-C adjudicate() from B1 script without package install."""
    import importlib.util

    path = REPO_ROOT / "scripts" / "run_baseline1_challenger.py"
    spec = importlib.util.spec_from_file_location("run_baseline1_challenger", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.adjudicate


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
        warn_if_unpinned(
            args.start, args.end, require_pin=args.require_pin, context="baseline2"
        )
        start_ms, end_ms = parse_window_ms(args.start, args.end)
    except ContractPinError as exc:
        print(f"[b2] pin error: {exc}", file=sys.stderr)
        return 2

    from quantflow.data.store import DataStore

    store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
    try:
        raw = store.query(SYMBOL, start=start_ms, end=end_ms, timeframe="1h")
    finally:
        store.close()
    if raw.empty:
        print("[b2] no bars in pin window", file=sys.stderr)
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
        f"[b2] pin {args.start}→{args.end} bars={len(df)} segments={len(segments)} "
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
            print(
                f"  seg{i + 1}/{len(segments)} OOS {oos_rets[-1]:+.2f}% "
                f"sh={oos_sharpes[-1]:.3f}"
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
        non_classic = [r for r in rows if r["label"] != "classic"]
        best_nc = (
            max(
                non_classic,
                key=lambda r: r.get("wfo_oos_mean_sharpe")
                if r.get("wfo_oos_mean_sharpe") is not None
                else -99,
            )
            if non_classic
            else None
        )
        grid_targets = [("classic", "trend_following", None)]
        if best_nc is not None:
            grid_targets.append(
                (best_nc["label"], best_nc["strategy"], best_nc.get("params"))
            )
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
                    f"  {label} fee={fee} slip={slip} "
                    f"ret={cell['return_pct']} sh={cell['sharpe']}"
                )

    adjudicate = _load_adjudicate()
    adj = adjudicate(rows, fee_rows)
    # B2-specific complementarity note attached to adjudication
    adj["complementarity"] = {
        "vs_baseline0": "B0 = multi-symbol classic trend RP; B2 = single-name anti-trend / vol-breakout families",
        "vs_baseline1": "B1 = non-MA trend-ish (donchian/roc/rsi); B2 = mean_reversion + volatility_breakout",
        "not_isomorphic": True,
    }
    print(f"\n[b2] verdict={adj['verdict']} reason={adj['reason']}")

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    wfo_path = out_dir / "complementary_wfo.json"
    fee_path = out_dir / "fee_slip_grid.json"
    adj_path = out_dir / "adjudication.json"
    meta_path = out_dir / "run_meta.json"

    wfo_payload = {
        "symbol": SYMBOL,
        "entry_tf": "1h",
        "gate": args.gate,
        "window": pin.to_dict(),
        "train_months": TRAIN_MONTHS,
        "fwd_months": FWD_MONTHS,
        "note": "T013 complementary families vs classic; production fee on WFO",
        "rows": rows,
        "winner_by_oos_mean_sharpe": max(
            rows,
            key=lambda r: r.get("wfo_oos_mean_sharpe")
            if r.get("wfo_oos_mean_sharpe") is not None
            else -99,
        )["label"],
    }
    wfo_path.write_text(
        json.dumps(wfo_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    fee_path.write_text(
        json.dumps(
            {"grid": fee_rows, "cells": FEE_GRID, "note": "Full pin window"},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    adj_path.write_text(json.dumps(adj, indent=2, ensure_ascii=False), encoding="utf-8")
    meta = {
        "task": "T013",
        "contract_docs": [
            "docs/research/Candidate-Baseline-0.md",
            "docs/research/Candidate-Baseline-1.md",
            "docs/research/Candidate-Baseline-2.md",
            "docs/research/baseline-contract-index.md",
        ],
        "ran_at": datetime.now(UTC).isoformat(),
        "start": args.start,
        "end": args.end,
        "start_ms": pin.start_ms,
        "end_ms": pin.end_ms,
        "data_fingerprint": pin.data_fingerprint,
        "verdict": adj["verdict"],
        "upgrade_to_baseline1": adj.get("upgrade_to_baseline1"),
        "outputs": {
            "complementary_wfo": str(wfo_path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "fee_slip_grid": str(fee_path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "adjudication": str(adj_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        },
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[b2] wrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
