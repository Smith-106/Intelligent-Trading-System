#!/usr/bin/env python3
"""Paper historical replay — accumulate bar-return history for F4/F5 diagnostics.

P1-verify step 3 tool: replay local parquet bars through a TradingSession in
paper mode (same on_bar event path as live), then feed the accumulated
_returns_history into F4 (bootstrap_cvar) and F5 returns-bootstrap
(monte_carlo_stress). This is the "simulate live with historical data" path
documented in the P1 live-verification checklist.

Why this is valid and `quantflow research`/BacktestEngine is NOT: BacktestEngine
is a separate vectorized engine that never calls on_bar, never touches the
RiskEngine/PositionSizer, never fills _returns_history — so it cannot exercise
the P1 wiring. This script drives the real on_bar path.

Scope: F4 (bootstrap CVaR CI) + F5 returns-bootstrap both consume per-bar
returns, which on_bar already feeds into _risk_engine._returns_history
(ISS-20260719-001). F5 trade-shuffle is NOT covered here — it needs per-trade
returns, which paper sessions do not yet collect (a separate enhancement).

Signal-density caveat: trend_following has required_regime="trending", so
on_bar gates the strategy out unless the MarketRegimeDetector sees a trending
stretch. On real BTC/USDT 1h parquet (2024-12..2025-06) only ~21/676 bars are
trending, so a replay there accumulates mostly-zero bar returns. To get
non-zero F4/F5 diagnostics from real data, either (a) replay a known-trending
window, (b) use a strategy that trades in non-trending regimes, or (c) tune
strategy params. This is a data/strategy-property, not a P1 wiring issue — the
on_bar → _returns_history → F4/F5 chain itself is verified by the data-flow
unit tests (TestPaperReplayFeedsF4F5Diagnostics) on synthetic high-vol data.

Usage:
    python scripts/replay_paper_f4f5.py --symbol BTC/USDT --timeframe 1h
    python scripts/replay_paper_f4f5.py --symbol BTC/USDT --max-bars 200
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from quantflow.common.config import AppConfig  # noqa: E402
from quantflow.common.models import Bar  # noqa: E402
from quantflow.data.store import DataStore  # noqa: E402
from quantflow.execution.engine import ExecutionEngine  # noqa: E402
from quantflow.execution.paper_gateway import PaperGateway  # noqa: E402
from quantflow.signal.risk_metrics import bootstrap_cvar  # noqa: E402
from quantflow.strategy.engine import TradingSession  # noqa: E402
from quantflow.strategy.templates.trend_following import TrendFollowingStrategy  # noqa: E402
from quantflow.strategy.validation.monte_carlo import monte_carlo_stress  # noqa: E402


def load_bars(
    parquet_dir: str, symbol: str, timeframe: str | None, max_bars: int | None
) -> pd.DataFrame:
    """Load historical bars from local parquet (same store the paper loop uses)."""
    store = DataStore(parquet_dir, ":memory:")
    try:
        df = store.query(symbol, timeframe=timeframe)
        if df.empty:
            df = store.query(symbol)
    finally:
        store.close()
    if df.empty:
        raise SystemExit(f"No local parquet data for {symbol}; run `quantflow download` first.")
    if max_bars is not None:
        df = df.head(max_bars)
    return df


def build_session() -> TradingSession:
    """Build a paper TradingSession with PaperGateway injected directly,
    bypassing start() so no Prometheus server or live data loop is started."""
    cfg = AppConfig()
    cfg.execution.mode = "paper"
    cfg.risk.kill_switch_enabled = False  # replay is a controlled sim, not live
    cfg.risk.max_drawdown = -0.90  # do not trip kill-switch mid-replay
    cfg.risk.vol_target_pct = None  # OFF: byte-for-byte baseline (F3 is unit-tested separately)

    strategy = TrendFollowingStrategy()
    session = TradingSession(cfg, [strategy])
    # Inject the paper gateway directly so submit_order simulates fills without
    # going through start()'s Prometheus/network init or the live data loop.
    session._execution = ExecutionEngine(
        event_bus=session._event_bus,
        gateway=PaperGateway({"initial_capital": 100_000.0, "taker_fee": cfg.execution.taker_fee}),
        timeout=cfg.execution.order_timeout,
    )
    return session


async def replay(session: TradingSession, bars_df: pd.DataFrame, symbol: str) -> list[float]:
    """Feed each bar through on_bar; return the accumulated returns history."""
    session._running = True
    # Initialize strategy contexts the way start() would.
    from quantflow.strategy.base import StrategyContext

    for strategy in session._strategies:
        ctx = StrategyContext()
        strategy.on_init(ctx)
        session._contexts[strategy.name] = ctx

    for row in bars_df.itertuples(index=False):
        bar = Bar(
            symbol=symbol,
            timestamp=int(row.timestamp),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
        await session.on_bar(bar)
    return list(session._risk_engine._returns_history)


def run_f4(history: list[float]) -> dict:
    """F4: bootstrap CVaR confidence interval (diagnostic, non-gate)."""
    return bootstrap_cvar(history, confidence=0.95, n_bootstrap=1000, seed=0)


def run_f5_returns_bootstrap(history: list[float], capital: float) -> list:
    """F5: returns-bootstrap stress (diagnostic, non-gate). trade-shuffle
    skipped because per-trade returns are not collected by paper sessions."""
    return monte_carlo_stress(
        trade_returns=None,
        bar_returns=history,
        n_paths=1000,
        initial_capital=capital,
        seed=0,
    )


def print_results(n_bars: int, history: list[float], f4: dict, f5: list) -> None:
    print("\n=== Paper historical replay — F4/F5 diagnostics ===")
    print(f"bars replayed       : {n_bars}")
    print(f"returns accumulated : {len(history)} (first bar skipped, no look-ahead)")
    if not history:
        print("  [!] empty history — strategy never opened a position; check data/signal")
        return
    print("\n--- F4: bootstrap CVaR (diagnostic) ---")
    print(f"  point estimate    : {f4['point']:.5f}  (positive = loss magnitude)")
    print(f"  95% CI            : [{f4['ci_low']:.5f}, {f4['ci_high']:.5f}]")
    print(
        f"  ci_width          : {f4['ci_high'] - f4['ci_low']:.5f}  (narrower as n grows; checklist P1.3-V1)"
    )
    print(f"  n / n_bootstrap   : {f4['n']} / {f4['n_bootstrap']}")
    print("  cvar_limit (gate) : -0.05  (CVaR loss > 0.05 → gate blocks; checklist P1.3-V2)")
    print("\n--- F5: returns-bootstrap stress (diagnostic) ---")
    for r in f5:
        if r.method != "returns_bootstrap":
            continue
        print(f"  method            : {r.method}")
        print(f"  observed terminal : {r.observed_terminal_return:.5f}")
        print(
            f"  P5/P95 terminal   : [{r.p5_terminal_return:.5f}, {r.p95_terminal_return:.5f}]  (checklist P1.2-V2)"
        )
        print(
            f"  prob_worse_dd     : {r.prob_worse_drawdown:.3f}  (<=0.5 healthy, >0.7 NO-GO; checklist P1.2-V1)"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--max-bars", type=int, default=None, help="limit replay to first N bars")
    ap.add_argument("--parquet-dir", default="./data/parquet")
    ap.add_argument("--capital", type=float, default=100_000.0)
    args = ap.parse_args()

    bars_df = load_bars(args.parquet_dir, args.symbol, args.timeframe, args.max_bars)
    session = build_session()
    history = asyncio.run(replay(session, bars_df, args.symbol))
    f4 = run_f4(history)
    f5 = run_f5_returns_bootstrap(history, args.capital)
    print_results(len(bars_df), history, f4, f5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
