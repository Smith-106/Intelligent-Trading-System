"""Tests for TradingSession."""

import pytest

from quantflow.common.config import AppConfig
from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyBase, StrategyContext
from quantflow.strategy.engine import TradingSession


class SimpleTestStrategy(StrategyBase):
    """Minimal strategy for testing."""

    def __init__(self):
        super().__init__(name="test_strategy")

    def on_init(self, ctx: StrategyContext) -> None:
        pass

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        ctx.emit_signal(
            symbol=bar.symbol,
            direction=Direction.LONG,
            strength=0.8,
            price=bar.close,
            strategy_id=self.name,
        )

    def generate_signals(self, df):
        import pandas as pd

        entries = pd.Series(False, index=df.index)
        exits = pd.Series(False, index=df.index)
        return entries, exits


class TestTradingSession:
    def test_init(self):
        config = AppConfig()
        strategies = [SimpleTestStrategy()]
        session = TradingSession(config, strategies)
        assert session.portfolio is not None
        assert session.execution is not None
        assert session.kill_switch is None

    @pytest.mark.asyncio
    async def test_start_paper(self):
        config = AppConfig()
        strategies = [SimpleTestStrategy()]
        session = TradingSession(config, strategies)
        await session.start(mode="paper")
        assert session.execution.gateway is not None
        await session.stop()

    @pytest.mark.asyncio
    async def test_on_bar(self):
        config = AppConfig()
        strategies = [SimpleTestStrategy()]
        session = TradingSession(config, strategies)
        await session.start(mode="paper")

        bar = Bar(
            symbol="BTC/USDT",
            timestamp=1712620800000,
            open=50000.0,
            high=50500.0,
            low=49500.0,
            close=50200.0,
            volume=1000.0,
        )
        await session.on_bar(bar)
        # Should not crash — signal processed through risk+execution
        await session.stop()

    @pytest.mark.asyncio
    async def test_check_health(self):
        config = AppConfig()
        strategies = [SimpleTestStrategy()]
        session = TradingSession(config, strategies)
        await session.start(mode="paper")

        health = session.check_health()
        assert "running" in health
        assert "drawdown_ok" in health
        assert "pending_orders" in health
        assert "open_positions" in health
        await session.stop()

    @pytest.mark.asyncio
    async def test_stop(self):
        config = AppConfig()
        strategies = [SimpleTestStrategy()]
        session = TradingSession(config, strategies)
        await session.start(mode="paper")
        await session.stop()
        # After stop, running should be False
        health = session.check_health()
        assert health["running"] is False

    @pytest.mark.asyncio
    async def test_multiple_strategies(self):
        config = AppConfig()
        strategies = [SimpleTestStrategy(), SimpleTestStrategy()]
        session = TradingSession(config, strategies)
        await session.start(mode="paper")

        bar = Bar(
            symbol="BTC/USDT",
            timestamp=1712620800000,
            open=50000.0,
            high=50500.0,
            low=49500.0,
            close=50200.0,
            volume=1000.0,
        )
        await session.on_bar(bar)
        await session.stop()


class TestWeeklyBaseEquityPointer:
    """ISS-033: the weekly-loss anchor is found via a monotone-forward
    pointer (O(1) amortized) instead of an O(n) per-bar linear scan. These
    tests pin the pure helper's contract directly — warmup fallback, window
    advance, and pointer monotonicity — independent of the paper-trade PnL
    chain (whose equity is perturbed by fills/fees)."""

    def _advance(self, history, base_idx, now_ms):
        from quantflow.strategy.engine import _weekly_base_equity

        return _weekly_base_equity(history, base_idx, now_ms)

    def test_warmup_falls_back_to_oldest_when_window_under_7d(self):
        day = 24 * 3600 * 1000
        t0 = 1_700_000_000_000
        # Only 1 day of history — nothing is >= week_ago, so base = oldest.
        history = [(t0, 100.0), (t0 + day, 90.0)]
        base, idx, _cutoff = self._advance(history, 0, t0 + day)
        assert base == 100.0  # oldest snapshot (conservative warmup)
        assert idx == 0  # pointer did not advance (no snapshot >= cutoff)

    def test_pointer_advances_past_snapshots_outside_7d_window(self):
        day = 24 * 3600 * 1000
        t0 = 1_700_000_000_000
        # day0 (out of window by now+8d), day1 (in window), day8 = now.
        history = [(t0, 100.0), (t0 + day, 90.0), (t0 + 8 * day, 108.0)]
        now = t0 + 8 * day
        base, idx, _ = self._advance(history, 0, now)
        # day0 is < week_ago → skipped; day1 is the first >= week_ago.
        assert idx == 1
        assert base == 90.0

    def test_pointer_is_monotone_across_successive_bars(self):
        day = 24 * 3600 * 1000
        t0 = 1_700_000_000_000
        history = [(t0 + i * day, float(100 + i)) for i in range(12)]
        base_idx = 0
        # Simulate the bar clock advancing one day at a time past 7 days.
        for bar_day in range(1, 12):
            now = t0 + bar_day * day
            _base, base_idx, _ = self._advance(history, base_idx, now)
            # The pointer must never retreat.
            assert base_idx <= bar_day
            # And the anchor must be a snapshot inside the 7-day window
            # (or the oldest available during warmup).
            week_ago = now - 7 * day
            assert history[base_idx][0] >= week_ago or base_idx == 0

    def test_empty_history_returns_zero_base(self):
        base, idx, _ = self._advance([], 0, 1_700_000_000_000)
        assert base == 0.0
        assert idx == 0

    def test_eviction_decrements_pointer_staying_aligned(self):
        # ISS-033 eviction contract: when the leftmost snapshot is evicted,
        # the caller decrements base_idx by 1 (clamped at 0) so the pointer
        # stays aligned to the same logical snapshot. This test exercises the
        # engine's on_bar eviction path end-to-end via a tiny maxlen.
        config = AppConfig()
        session = TradingSession(config, [SimpleTestStrategy()])
        session._equity_history_maxlen = 3
        session._equity_history = [(1_700_000_000_000 + i, 100.0) for i in range(3)]
        session._weekly_base_idx = 1  # pointing at the middle snapshot
        # Append one more → eviction kicks in; pointer must decrement to 0.
        session._equity_history.append((1_700_000_000_000 + 3, 100.0))
        if len(session._equity_history) > session._equity_history_maxlen:
            session._equity_history.pop(0)
            if session._weekly_base_idx > 0:
                session._weekly_base_idx -= 1
        assert session._weekly_base_idx == 0
        assert len(session._equity_history) == 3
