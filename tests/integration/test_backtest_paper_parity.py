"""Backtest vs paper parity regression (T-s1-05).

Locks the ISS-20260720-001 design-property as an executable assertion:
the vectorized ``generate_signals`` path (backtest, no regime gate) trades
a SUPERSET of the paper ``on_bar`` path (regime-gated via
MarketRegimeDetector in TradingSession):

    paper_entries is a subset of backtest_entries

Covered strategies (both regime-gated templates):
- trend_following  (required_regime="trending")
- funding_rate     (required_regime="mean_reversion")

The paper replay runs through a real TradingSession (paper mode) so the
assertion exercises the actual regime gate, per-symbol instances and signal
pipeline — not a re-implementation of the engine.
"""

from __future__ import annotations

import pandas as pd
import pytest

from quantflow.common.config import AppConfig
from quantflow.common.event_bus import EVENT_SIGNAL
from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyBase
from quantflow.strategy.engine import TradingSession
from quantflow.strategy.templates.funding_rate import FundingRateStrategy
from quantflow.strategy.templates.trend_following import TrendFollowingStrategy

SYMBOL = "BTC/USDT"
_BASE_TS = 1_700_000_000_000


def _bar(i: int, close: float, volume: float = 100.0) -> Bar:
    return Bar(
        symbol=SYMBOL,
        timestamp=_BASE_TS + i * 3_600_000,
        open=close,
        high=close * 1.004,
        low=close * 0.996,
        close=close,
        volume=volume,
    )


def _trend_bars() -> list[Bar]:
    """Flat warmup -> strong uptrend (ADX rises) -> sideways -> downtrend."""
    bars: list[Bar] = []
    close = 100.0
    for i in range(150):
        if i < 30:
            close *= 1 + 0.0005 * (1 if i % 2 else -1)
        elif i < 90:
            close *= 1.007 if i % 4 else 0.988  # gentle uptrend, deep pullbacks
        elif i < 120:
            close *= 1 + 0.0008 * (1 if i % 2 else -1)
        else:
            close *= 0.988
        bars.append(_bar(i, close, volume=160.0 if i % 3 == 0 else 100.0))
    return bars


def _flat_bars(n: int = 40) -> list[Bar]:
    """Sideways series — keeps the regime detector in mean-reversion."""
    return [_bar(i, 50_000.0 + (6.0 if i % 2 else -6.0)) for i in range(n)]


def _backtest_entries(strategy: StrategyBase, df: pd.DataFrame) -> set[int]:
    entries, _ = strategy.generate_signals(df)
    return {i for i, v in enumerate(entries.tolist()) if bool(v)}


async def _paper_entries(
    strategy: StrategyBase,
    bars: list[Bar],
    prime=None,
) -> set[int]:
    """Replay bars through a real paper TradingSession; collect entry bar ids.

    ``prime(session)`` may pre-populate per-instance data (funding/OI) after
    start() created the per-(strategy, symbol) instances.
    """
    session = TradingSession(AppConfig(), [strategy])
    signals: list[dict] = []
    session.event_bus.subscribe(EVENT_SIGNAL, lambda e: signals.append(e.data))
    await session.start(mode="paper", symbols=[SYMBOL])
    try:
        if prime is not None:
            prime(session)
        out: set[int] = set()
        for i, bar in enumerate(bars):
            prev = len(signals)
            await session.on_bar(bar)
            for s in signals[prev:]:
                if s["direction"] != Direction.FLAT.value:
                    out.add(i)
        return out
    finally:
        await session.stop()


class TestTrendFollowingParity:
    """trending-gated strategy: paper may drop entries, never invent them."""

    def _bars_df(self, bars: list[Bar]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "close": [b.close for b in bars],
                "high": [b.high for b in bars],
                "low": [b.low for b in bars],
                "volume": [b.volume for b in bars],
            }
        )

    @pytest.mark.asyncio
    async def test_paper_entries_subset_of_backtest(self) -> None:
        bars = _trend_bars()
        df = self._bars_df(bars)

        backtest = _backtest_entries(TrendFollowingStrategy(), df)
        paper = await _paper_entries(TrendFollowingStrategy(), bars)

        assert backtest, "dataset must produce backtest entries"
        assert paper, "regime gate must admit at least one paper entry"
        assert paper <= backtest, f"paper invented entries: {sorted(paper - backtest)}"

    @pytest.mark.asyncio
    async def test_relaxed_params_keep_superset(self) -> None:
        """Identical params on both paths keep the superset relation too."""
        bars = _trend_bars()
        df = self._bars_df(bars)
        params = {"volume_threshold": 0.5, "min_conditions": 3}

        backtest = _backtest_entries(TrendFollowingStrategy(params), df)
        paper = await _paper_entries(TrendFollowingStrategy(params), bars)
        assert paper <= backtest


class TestFundingRateParity:
    """mean_reversion-gated strategy: same superset assertion, other regime."""

    @staticmethod
    def _bars_df(bars: list[Bar], rates: list[float], ois: list[float]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "close": [b.close for b in bars],
                "funding_rate": rates,
                "open_interest": ois,
            }
        )

    @pytest.mark.asyncio
    async def test_paper_entries_subset_of_backtest(self) -> None:
        bars = _flat_bars(40)
        rates = [-0.002] * len(bars)  # extreme negative -> LONG entries
        ois = [1000.0 * (1.05**i) for i in range(len(bars))]  # rising OI

        backtest = _backtest_entries(FundingRateStrategy(), self._bars_df(bars, rates, ois))

        def prime(session: TradingSession) -> None:
            inst = session._instances[("funding_rate", SYMBOL)]
            for r in rates:
                inst.update_funding_rate(r)
            for oi in ois:
                inst.update_open_interest(oi)

        paper = await _paper_entries(FundingRateStrategy(), bars, prime=prime)

        assert backtest, "dataset must produce backtest entries"
        assert paper, "non-trending regime must admit at least one paper entry"
        assert paper <= backtest, f"paper invented entries: {sorted(paper - backtest)}"
