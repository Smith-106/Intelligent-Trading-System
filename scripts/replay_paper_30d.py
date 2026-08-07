#!/usr/bin/env python3
"""30-day paper replay CLI — production-path simulation on real historical data.

C1: replay the last N days of local parquet bars through TradingSession.on_bar
in paper mode (the same event path as live), collecting fills, risk events and
a per-bar equity curve into a report (JSON + console summary).

Core logic lives in quantflow.strategy.research.paper_replay (unit-tested);
this script only loads the data window and prints the report.

Usage:
    python scripts/replay_paper_30d.py --strategy mean_reversion
    python scripts/replay_paper_30d.py --strategy trend_following --days 30
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from quantflow.data.store import DataStore  # noqa: E402
from quantflow.strategy.research.paper_replay import (  # noqa: E402
    STRATEGIES,
    RecordingSink,
    aggregate,
    build_session,
    replay,
)


def load_bars(
    parquet_dir: str, symbol: str, timeframe: str, days: int, end_ms: int
) -> pd.DataFrame:
    """Load the trailing ``days`` window of bars from local parquet."""
    store = DataStore(parquet_dir, ":memory:")
    try:
        df = store.query(
            symbol,
            start=end_ms - days * 86_400_000,
            end=end_ms,
            timeframe=timeframe,
        )
        if df.empty:
            df = store.query(symbol, start=end_ms - days * 86_400_000, end=end_ms)
    finally:
        store.close()
    if df.empty:
        raise SystemExit(
            f"No local parquet data for {symbol} in the last {days}d; "
            "run `quantflow download` first."
        )
    return df


def print_summary(report: Any) -> None:
    print("\n=== 30-day paper replay — production path ===")
    print(f"bars replayed       : {report['bars']} (1h)")
    print(f"orders / fills      : {report['orders']} / {report['fills']}")
    print(f"initial capital     : {report['initial_capital']:,.0f}")
    print(f"final equity        : {report['final_equity']:,.2f}")
    print(f"return              : {report['return_pct']:+.4f}%")
    print(f"max drawdown        : {report['max_drawdown_pct']:.4f}%")
    print(f"sharpe (annualized) : {report['sharpe_annualized']}")
    print("risk events (by reason):")
    for reason, count in report["risk_events"].items():
        print(f"  {reason:<30} {count}")
    if report["alerts"]:
        print(f"alerts through sink  : {len(report['alerts'])}")
        for a in report["alerts"][:5]:
            print(f"  [{a['level']}] {a['message'][:80]}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Replay the last N days of local parquet bars through the "
        "production paper path and report trades/equity/risk outcomes."
    )
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--end", default=None, help="window end YYYY-MM-DD (default: now)")
    ap.add_argument(
        "--strategy",
        default="mean_reversion",
        choices=list(STRATEGIES),
        help="strategy to replay (mean_reversion trades non-trending bars and "
        "yields a dense book; trend_following is regime-gated on real data)",
    )
    ap.add_argument("--capital", type=float, default=100_000.0)
    ap.add_argument(
        "--direction-gate",
        action="store_true",
        help="A/B switch: suppress mean-reversion entries while the direction "
        "gate is closed (bear-regime protection). Default off = byte-for-byte baseline.",
    )
    ap.add_argument(
        "--gate-type",
        default="sma",
        choices=["sma", "ema", "slope", "dual", "nested"],
        help="gate variant: sma=close>=SMA200 (default); ema=close>=EMA55; "
        "slope=close>=SMA200 AND SMA rising (AA); dual=EMA20>=EMA50 golden-cross "
        "(AB); nested=4h SMA50 direction gate over 1h entries (A/a)",
    )
    ap.add_argument("--gate-sma-period", type=int, default=200)
    ap.add_argument("--parquet-dir", default="./data/parquet")
    ap.add_argument(
        "--out",
        default="./data/paper_replay/report.json",
        help="JSON report output path",
    )
    args = ap.parse_args()

    end_ms = int(pd.Timestamp(args.end).timestamp() * 1000) if args.end else int(time.time() * 1000)
    bars_df = load_bars(args.parquet_dir, args.symbol, args.timeframe, args.days, end_ms)
    sink = RecordingSink()
    session = build_session(args.strategy, args.capital, sink)
    fills: list[dict[str, object]] = []
    risk_events: list[dict[str, object]] = []
    curve = asyncio.run(
        replay(
            session,
            bars_df,
            args.symbol,
            fills,
            risk_events,
            direction_gate=args.gate_type if args.direction_gate else False,
            gate_sma_period=args.gate_sma_period,
        )
    )
    report = aggregate(curve, fills, risk_events, sink.alerts, args.capital)
    report["meta"] = {
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "days": args.days,
        "strategy": args.strategy,
        "window_end": pd.Timestamp(end_ms, unit="ms").isoformat(),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print_summary(report)
    print(f"\nreport written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
