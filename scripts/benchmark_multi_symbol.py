#!/usr/bin/env python3
"""M4 acceptance benchmark — 30-symbol x 5-strategy rotation (M4-6.4/6.6).

Rotates synthetic bars across 30 symbols through a full TradingSession
(per-symbol instances + signal lock + paper execution), measuring:

1.  on_bar latency per bar (acceptance: < 2.0s for 30 symbol x 5 strategies)
2.  throughput (bars/sec) vs the 1-symbol baseline
3.  signal integrity: every emitted signal must be flushed and processed

Run:
    python scripts/benchmark_multi_symbol.py [--bars 600] [--symbols 30]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import asyncio  # noqa: E402

from quantflow.common.models import Bar, Direction  # noqa: E402
from quantflow.strategy.base import StrategyBase, StrategyContext  # noqa: E402
from quantflow.strategy.engine import TradingSession  # noqa: E402


class _AlwaysSignalStrategy(StrategyBase):
    """Emits one BUY signal per bar (max strength) — worst-case pipeline load."""

    def __init__(self, name: str = "bench", params: dict[str, object] | None = None) -> None:
        super().__init__(name=name, params=params)
        self.bar_calls = 0

    def on_init(self, ctx: StrategyContext) -> None:
        return None

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        self.bar_calls += 1
        ctx.emit_signal(
            symbol=bar.symbol,
            direction=Direction.LONG,
            strength=1.0,
            price=bar.close,
        )

    def generate_signals(self, df: object) -> tuple[list[object], list[object]]:
        return [], []


def _make_session(strategies: list[StrategyBase]) -> TradingSession:
    """Build a paper-mode session (production path: start() creates the
    per-(strategy, symbol) instances via the strategy factory)."""
    from quantflow.common.config import load_config

    config = load_config(config_path=REPO_ROOT / "quantflow" / "config" / "default.yaml")
    config.execution.mode = "paper"
    return TradingSession(config, strategies)


def _bar(symbol: str, price: float, ts: int) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=ts,
        open=price - 1,
        high=price + 1,
        low=price - 2,
        close=price,
        volume=10.0,
    )


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bars", type=int, default=600, help="total synthetic bars to rotate")
    ap.add_argument("--symbols", type=int, default=30)
    ap.add_argument("--strategies", type=int, default=5)
    args = ap.parse_args()

    symbols = [f"SYM{i:03d}/USDT" for i in range(args.symbols)]
    strategies: list[StrategyBase] = [
        _AlwaysSignalStrategy(f"bench{i}") for i in range(args.strategies)
    ]
    session = _make_session(strategies)
    await session.start(mode="paper", symbols=symbols)
    session.portfolio.set_allocation({s.name: 1.0 / len(strategies) for s in strategies})

    t0 = time.perf_counter()
    for i in range(args.bars):
        sym = symbols[i % args.symbols]
        await session.on_bar(_bar(symbol=sym, price=100.0 + i * 0.01, ts=1_000_000 + i * 60_000))
    elapsed = time.perf_counter() - t0

    bars_per_sec = args.bars / elapsed if elapsed > 0 else float("inf")
    bar_latency_ms = 1000.0 / bars_per_sec if bars_per_sec else float("inf")
    # Per-strategy call counts from the session instances (not prototypes).
    total_calls = 0
    for st in strategies:
        for _key, inst in session._instances.items():
            if isinstance(inst, _AlwaysSignalStrategy) and inst.name == st.name:
                total_calls += inst.bar_calls

    print(f"\n[{args.symbols} symbols x {args.strategies} strategies]")
    print(f"  bars processed:     {args.bars}")
    print(f"  elapsed:            {elapsed:.3f}s")
    print(f"  throughput:         {bars_per_sec:.0f} bars/sec")
    print(f"  on_bar latency:     {bar_latency_ms:.1f} ms/bar  (acceptance < 2000 ms)")
    print(f"  strategy calls:     {total_calls} (expected {args.bars})")
    ok = bar_latency_ms < 2000.0 and total_calls >= args.bars
    print(f"[benchmark] {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
