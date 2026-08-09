#!/usr/bin/env python3
"""Establish P0-verify regression guard baseline.

Runs 4 strategies' generate_signals() on BTC/USDT parquet data, feeds the
resulting entry/exit signals through BacktestEngine.run_backtest(), and
collects deterministic metrics (total_return, sharpe_ratio, max_drawdown,
num_trades, trade_returns hash, entry/exit signal hash).

Output is a JSON file used by tests/unit/test_p0_regression_guard.py to
detect unintended behaviour changes after code modifications.

Usage:
    python scripts/establish_p0_baseline.py
    python scripts/establish_p0_baseline.py --output .workflow/artifacts/p0-baseline/test-results.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from quantflow.data.store import DataStore  # noqa: E402
from quantflow.strategy.catalog import get_strategy_definitions  # noqa: E402
from quantflow.strategy.research.backtest import BacktestEngine  # noqa: E402

# Strategies included in the P0 regression guard baseline.
STRATEGIES = [
    "trend_following",
    "volatility_breakout",
    "mean_reversion",
    "momentum_rotation",
]

# Backtest parameters (fixed for determinism).
INITIAL_CAPITAL = 100_000.0
FEE = 0.001
SYMBOL = "BTC/USDT"


def load_bars(parquet_dir: str) -> pd.DataFrame:
    """Load BTC/USDT 1h bars from local parquet store.

    Always filter by timeframe so multi-TF co-resident partitions (post-MTF
    expansion) do not mix intervals into a single close series.
    """
    store = DataStore(parquet_dir, ":memory:")
    try:
        df = store.query(SYMBOL, timeframe="1h")
        if df.empty:
            # Legacy stores without a timeframe column / filter.
            df = store.query(SYMBOL)
    finally:
        store.close()
    if df.empty:
        raise SystemExit(f"No local parquet data for {SYMBOL}; run `quantflow download` first.")
    return df


def pin_bars(
    df: pd.DataFrame,
    *,
    end_ms: int | None = None,
    bar_count: int | None = None,
) -> pd.DataFrame:
    """Pin a deterministic research window so growing parquet cannot drift goldens.

    Preference: ``end_ms`` (inclusive) then optional ``bar_count`` tail/head.
    Without pins, returns timestamp-sorted full frame (legacy establish mode).
    """
    out = df.sort_values("timestamp").reset_index(drop=True)
    if end_ms is not None:
        out = out[out["timestamp"].astype("int64") <= int(end_ms)].reset_index(drop=True)
    if bar_count is not None:
        n = int(bar_count)
        if n <= 0:
            raise SystemExit("--bar-count must be positive")
        # Keep the earliest n bars after end filter (stable prefix of history).
        out = out.iloc[:n].reset_index(drop=True)
    return out


def hash_series(s: pd.Series) -> str:
    """SHA-256 hash of a Series' values (first 16 hex chars)."""
    raw = json.dumps(s.tolist(), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def hash_trade_returns(returns: list[float]) -> str:
    """SHA-256 hash of trade returns list (first 16 hex chars)."""
    raw = json.dumps([f"{r:.15g}" for r in returns])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def collect_baseline(df: pd.DataFrame, strategy_name: str) -> dict[str, Any]:
    """Run backtest for one strategy and collect deterministic metrics."""
    definitions = get_strategy_definitions()
    definition = definitions[strategy_name]
    strategy = definition.factory()

    # Generate vectorized entry/exit signals
    entries, exits = strategy.generate_signals(df)

    # Hash the raw signal Series for strict parity
    entry_hash = hash_series(entries.astype(bool))
    exit_hash = hash_series(exits.astype(bool))

    # Run backtest
    engine = BacktestEngine()
    result = engine.run_backtest(
        close=df["close"],
        entries=entries,
        exits=exits,
        initial_capital=INITIAL_CAPITAL,
        fee=FEE,
        strategy_id=strategy_name,
        symbol=SYMBOL,
    )

    return {
        "strategy_name": strategy_name,
        "total_return": result.total_return,
        "sharpe_ratio": result.sharpe_ratio,
        "max_drawdown": result.max_drawdown,
        "num_trades": result.num_trades,
        "win_rate": result.win_rate,
        "profit_factor": result.profit_factor,
        "annual_return": result.annual_return,
        "sortino_ratio": result.sortino_ratio,
        "final_capital": result.final_capital,
        "trade_returns_hash": hash_trade_returns(result.trade_returns),
        "entry_signal_hash": entry_hash,
        "exit_signal_hash": exit_hash,
        "entry_count": int(entries.sum()),
        "exit_count": int(exits.sum()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Establish P0 regression baseline")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".workflow/artifacts/p0-baseline/test-results.json"),
        help="Output path for baseline JSON",
    )
    parser.add_argument(
        "--parquet-dir",
        default="./data/parquet",
        help="Parquet data directory",
    )
    parser.add_argument(
        "--end-ms",
        type=int,
        default=None,
        help="Inclusive end timestamp (ms UTC). Pin so goldens do not drift as parquet grows.",
    )
    parser.add_argument(
        "--bar-count",
        type=int,
        default=None,
        help="After end filter, keep the first N bars (stable prefix).",
    )
    args = parser.parse_args()

    print(f"Loading BTC/USDT data from {args.parquet_dir}...")
    raw = load_bars(args.parquet_dir)
    print(f"  bars loaded (raw): {len(raw)}")
    df = pin_bars(raw, end_ms=args.end_ms, bar_count=args.bar_count)
    if df.empty:
        raise SystemExit("Pinned window is empty; relax --end-ms / --bar-count")
    start_ms = int(df["timestamp"].astype("int64").iloc[0])
    end_ms = int(df["timestamp"].astype("int64").iloc[-1])
    print(f"  bars after pin: {len(df)}  start_ms={start_ms}  end_ms={end_ms}")

    baseline: dict[str, Any] = {
        "version": "1.1.0",
        "symbol": SYMBOL,
        "bar_count": len(df),
        "start_ms": start_ms,
        "end_ms": end_ms,
        "timeframe": "1h",
        "initial_capital": INITIAL_CAPITAL,
        "fee": FEE,
        "strategies": {},
    }

    for strategy_name in STRATEGIES:
        print(f"Collecting baseline for {strategy_name}...")
        metrics = collect_baseline(df, strategy_name)
        baseline["strategies"][strategy_name] = metrics
        print(
            f"  return={metrics['total_return']:.6f}  sharpe={metrics['sharpe_ratio']:.4f}  "
            f"maxdd={metrics['max_drawdown']:.6f}  trades={metrics['num_trades']}"
        )

    # Write baseline
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2)

    print(f"\nBaseline written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
