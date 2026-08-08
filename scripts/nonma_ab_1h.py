#!/usr/bin/env python3
"""Non-MA signal families vs classic MA trend_following on BTC 1h + nested gate.

Fixed parameters only (no Optuna). Families:
  - classic      : trend_following default (MA multi-filter baseline)
  - donchian     : NonMaSignalStrategy channel breakout
  - volume_roc   : volume surge + ROC momentum
  - rsi_thrust   : RSI cross 50 + volume

    python scripts/nonma_ab_1h.py
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

VARIANTS: list[tuple[str, str, dict[str, Any] | None]] = [
    ("classic", "trend_following", None),
    ("donchian", "non_ma_signal", {"signal_family": "donchian"}),
    ("volume_roc", "non_ma_signal", {"signal_family": "volume_roc"}),
    ("rsi_thrust", "non_ma_signal", {"signal_family": "rsi_thrust"}),
]


async def _eval(
    strategy: str,
    params: dict[str, Any] | None,
    bars: pd.DataFrame,
    symbol: str,
    gate: str | bool = "nested",
) -> dict[str, float]:
    sink = RecordingSink()
    session = build_session(strategy, 100_000.0, sink, params=params)
    fills: list[dict[str, object]] = []
    risk: list[dict[str, object]] = []
    curve = await replay(session, bars, symbol, fills, risk, direction_gate=gate, entry_tf="1h")
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
    ap.add_argument("--out", default="data/paper_replay/nonma_ab_1h.json")
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

    print(
        f"[nonma] bars={len(df)} segments={len(segments)} gate={args.gate} "
        f"variants={[v[0] for v in VARIANTS]}"
    )

    rows: list[dict[str, Any]] = []
    for label, strategy, params in VARIANTS:
        print(f"\n=== {label} ({strategy}) ===")
        full = asyncio.run(_eval(strategy, params, df.drop(columns="dt"), args.symbol, args.gate))
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
            fwd = df[
                (df["dt"] >= pd.to_datetime(tr_end, unit="ms"))
                & (df["dt"] < pd.to_datetime(fwd_end, unit="ms"))
            ].drop(columns="dt")
            if len(fwd) < 50:
                continue
            oos = asyncio.run(_eval(strategy, params, fwd, args.symbol, args.gate))
            oos_rets.append(float(oos.get("return_pct", 0.0)))
            oos_sharpes.append(_sharpe(oos))
            oos_orders += float(oos.get("orders", 0.0))
            print(
                f"  seg{i + 1}/{len(segments)} OOS {oos_rets[-1]:+.2f}% "
                f"sharpe={oos_sharpes[-1]:.3f} orders={oos.get('orders', 0)}"
            )

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
        "note": "fixed params, no Optuna; non-MA families vs classic MA",
        "rows": rows,
        "winner_by_oos_mean_sharpe": ranked[0]["label"] if ranked else None,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n[nonma] written {out}")
    print(f"{'label':>12} {'full%':>8} {'fullSh':>7} {'OOSsum':>8} {'OOSsh':>7} {'pos':>6}")
    for r in rows:
        print(
            f"{r['label']:>12} "
            f"{r.get('full_return_pct', float('nan')):>+8.2f} "
            f"{(r.get('full_sharpe') or float('nan')):>7.3f} "
            f"{r.get('wfo_oos_sum_pct', float('nan')):>+8.2f} "
            f"{(r.get('wfo_oos_mean_sharpe') or float('nan')):>7.3f} "
            f"{r.get('wfo_pos_rate', '—'):>6}"
        )
    print(f"[nonma] winner={payload['winner_by_oos_mean_sharpe']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
