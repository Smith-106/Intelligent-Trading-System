"""W16: SimpleStrategy thin DX template."""

from __future__ import annotations

import pandas as pd

from quantflow.common.models import Bar
from quantflow.strategy.base import StrategyContext
from quantflow.strategy.catalog import get_strategy_definitions
from quantflow.strategy.templates.simple import SimpleStrategy


def _bars(n: int = 40, start: float = 100.0) -> list[Bar]:
    out: list[Bar] = []
    px = start
    for i in range(n):
        # mild uptrend then flat
        px = px * (1.002 if i < 25 else 0.999)
        out.append(
            Bar(
                symbol="BTC/USDT",
                timestamp=1_700_000_000_000 + i * 3_600_000,
                open=px,
                high=px * 1.001,
                low=px * 0.999,
                close=px,
                volume=1.0,
            )
        )
    return out


def test_catalog_registers_simple() -> None:
    defs = get_strategy_definitions(include_disabled=True)
    assert "simple" in defs
    strat = defs["simple"].factory({"fast_period": 5, "slow_period": 10})
    assert isinstance(strat, SimpleStrategy)


def test_generate_signals_sma_default() -> None:
    s = SimpleStrategy({"fast_period": 5, "slow_period": 10})
    bars = _bars(50)
    df = pd.DataFrame(
        {
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
        }
    )
    entries, _exits = s.generate_signals(df)
    assert len(entries) == len(df)
    assert entries.dtype == bool or str(entries.dtype) == "bool"
    # uptrend early → at least one entry expected
    assert bool(entries.any())


def test_on_bar_emits_without_error() -> None:
    s = SimpleStrategy({"fast_period": 3, "slow_period": 5})
    signals: list = []

    class _Ctx(StrategyContext):
        def emit_signal(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            signals.append((args, kwargs))

    ctx = _Ctx()
    s.on_init(ctx)
    for b in _bars(20):
        s.on_bar(ctx, b)
    # may or may not emit depending on path; must not crash
    assert isinstance(signals, list)


def test_override_hooks() -> None:
    class AlwaysLong(SimpleStrategy):
        def should_long(self, closes):  # type: ignore[no-untyped-def]
            return len(closes) >= 2

        def should_exit_long(self, closes):  # type: ignore[no-untyped-def]
            return False

    s = AlwaysLong({"fast_period": 2, "slow_period": 2})
    df = pd.DataFrame({"close": [1.0, 2.0, 3.0, 4.0]})
    entries, exits = s.generate_signals(df)
    assert bool(entries.iloc[1])
    assert not bool(exits.any())
