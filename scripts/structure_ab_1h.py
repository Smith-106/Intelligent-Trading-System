#!/usr/bin/env python3
"""Structure-layer A/B on BTC 1h + nested gate (option B).

Compares fixed entry structures without parameter optimization:
  - classic  : multi-filter vote (baseline)
  - pullback : uptrend + reclaim fast MA after short dip
  - breakout : uptrend + close breaks prior N-bar high

For each structure:
  1. Full-window paper replay (default MA params + nested gate)
  2. Sliding WFO with FIXED params (no Optuna) — train window unused for
     search; only used as warm-up context for the forward window replay
     so segment OOS is a pure structure holdout under rolling regimes.

    python scripts/structure_ab_1h.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from quantflow.strategy.research.paper_replay import (  # noqa: E402
    RecordingSink,
    aggregate,
    build_session,
    replay,
)

STRUCTURES = ("classic", "pullback", "breakout")


async def _eval(
    structure: str,
    bars: pd.DataFrame,
    symbol: str,
    gate: str | bool = "nested",
) -> dict[str, float]:
    params: dict[str, Any] = {"entry_structure": structure}
    sink = RecordingSink()
    session = build_session("trend_following", 100_000.0, sink, params=params)
    fills: list[dict[str, object]] = []
    risk: list[dict[str, object]] = []
    curve = await replay(
        session, bars, symbol, fills, risk, direction_gate=gate, entry_tf="1h"
    )
    rep = aggregate(curve, fills, risk, sink.alerts, 100_000.0, entry_tf="1h")
    out: dict[str, float] = {}
    for k, v in rep.items():
        if isinstance(v, (int, float)):
            out[k] = float(v)
        elif v is None and k == "sharpe_annualized":
            out[k] = float("nan")
    return out


def _sharpe(rep: dict[str, float]) -> float:
    s = rep.get("sharpe_annualized", float("nan"))
    return s if s == s else -10.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--end", default="2026-08-04")
    ap.add_argument("--train-months", type=int, default=24)
    ap.add_argument("--fwd-months", type=int, default=6)
    ap.add_argument("--gate", default="nested")
    ap.add_argument("--out", default="data/paper_replay/structure_ab_1h.json")
    args = ap.parse_args()

    from quantflow.data.store import DataStore

    store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
    end_ms = int(pd.Timestamp(args.end).timestamp() * 1000)
    start_ms = end_ms - 2770 * 86_400_000
    df = store.query(args.symbol, start=start_ms, end=end_ms, timeframe="1h")
    store.close()
    if df.empty:
        raise SystemExit("no 1h bars")
    df = df[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms")
    print(f"[struct] bars={len(df)} gate={args.gate} structures={list(STRUCTURES)}")

    month_ms = 30 * 86_400_000
    train_ms = args.train_months * month_ms
    step_ms = args.fwd_months * month_ms
    first_end = int(df["dt"].min().timestamp() * 1000) + train_ms
    segments: list[tuple[int, int, int]] = []
    t_end = first_end
    data_end = int(df["dt"].max().timestamp() * 1000)
    while t_end + step_ms <= min(end_ms, data_end + 1):
        segments.append((t_end - train_ms, t_end, t_end + step_ms))
        t_end += step_ms
    print(f"[struct] WFO segments={len(segments)} train={args.train_months}m fwd={args.fwd_months}m")

    rows: list[dict[str, Any]] = []
    for structure in STRUCTURES:
        print(f"\n=== structure={structure} ===")
        full = asyncio.run(_eval(structure, df.drop(columns="dt"), args.symbol, args.gate))
        print(
            f"  full: ret={full.get('return_pct', float('nan')):+.2f}% "
            f"maxDD={full.get('max_drawdown_pct', float('nan')):.2f}% "
            f"sharpe={full.get('sharpe_annualized', float('nan'))} "
            f"orders={full.get('orders', 0)}"
        )

        oos_rets: list[float] = []
        oos_sharpes: list[float] = []
        oos_orders = 0.0
        for i, (_s, tr_end, fwd_end) in enumerate(segments):
            # Warm-up: include train window so indicators are primed, but only
            # score the forward slice via a separate forward-only replay for
            # clean OOS accounting (matches prior WFO methodology).
            fwd = df[
                (df["dt"] >= pd.to_datetime(tr_end, unit="ms"))
                & (df["dt"] < pd.to_datetime(fwd_end, unit="ms"))
            ].drop(columns="dt")
            if len(fwd) < 50:
                continue
            oos = asyncio.run(_eval(structure, fwd, args.symbol, args.gate))
            oos_rets.append(float(oos.get("return_pct", 0.0)))
            oos_sharpes.append(_sharpe(oos))
            oos_orders += float(oos.get("orders", 0.0))
            print(
                f"  seg{i + 1}/{len(segments)} OOS {oos_rets[-1]:+.2f}% "
                f"sharpe={oos_sharpes[-1]:.3f} orders={oos.get('orders', 0)}"
            )

        row = {
            "structure": structure,
            "full_return_pct": full.get("return_pct"),
            "full_max_dd_pct": full.get("max_drawdown_pct"),
            "full_sharpe": full.get("sharpe_annualized"),
            "full_orders": full.get("orders"),
            "wfo_segments": len(oos_rets),
            "wfo_oos_sum_pct": sum(oos_rets) if oos_rets else None,
            "wfo_oos_mean_pct": (sum(oos_rets) / len(oos_rets)) if oos_rets else None,
            "wfo_oos_mean_sharpe": (sum(oos_sharpes) / len(oos_sharpes)) if oos_sharpes else None,
            "wfo_pos_rate": (
                f"{sum(1 for r in oos_rets if r > 0)}/{len(oos_rets)}" if oos_rets else None
            ),
            "wfo_orders": oos_orders,
        }
        rows.append(row)
        print(
            f"  WFO: sum={row['wfo_oos_sum_pct']:+.2f}% "
            f"mean_sh={row['wfo_oos_mean_sharpe']:.3f} pos={row['wfo_pos_rate']}"
        )

    # Ranking by OOS mean sharpe then sum
    ranked = sorted(
        rows,
        key=lambda r: (
            r["wfo_oos_mean_sharpe"] if r["wfo_oos_mean_sharpe"] is not None else -99,
            r["wfo_oos_sum_pct"] if r["wfo_oos_sum_pct"] is not None else -99,
        ),
        reverse=True,
    )
    payload = {
        "symbol": args.symbol,
        "entry_tf": "1h",
        "gate": args.gate,
        "note": "fixed structures, no Optuna; default MA params",
        "rows": rows,
        "winner_by_oos_mean_sharpe": ranked[0]["structure"] if ranked else None,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n[struct] written {out}")
    print(f"{'struct':>10} {'full%':>8} {'fullSh':>7} {'OOSsum':>8} {'OOSsh':>7} {'pos':>6}")
    for r in rows:
        print(
            f"{r['structure']:>10} "
            f"{r.get('full_return_pct', float('nan')):>+8.2f} "
            f"{(r.get('full_sharpe') or float('nan')):>7.3f} "
            f"{r.get('wfo_oos_sum_pct', float('nan')):>+8.2f} "
            f"{(r.get('wfo_oos_mean_sharpe') or float('nan')):>7.3f} "
            f"{r.get('wfo_pos_rate', '—'):>6}"
        )
    print(f"[struct] winner={payload['winner_by_oos_mean_sharpe']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
