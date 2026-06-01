"""Tests for TradingSession."""

import pytest

from quantflow.common.config import AppConfig
from quantflow.common.models import Bar, Direction, Signal
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