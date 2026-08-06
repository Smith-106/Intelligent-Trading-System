"""Tests for s5 follow-up: engine optimizer selection + allocation monitoring."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pandas as pd
import pytest

from quantflow.common.config import AppConfig
from quantflow.common.models import Bar
from quantflow.signal.optimizer import MeanVarianceOptimizer, RiskParityOptimizer
from quantflow.strategy.base import StrategyBase, StrategyContext
from quantflow.strategy.engine import TradingSession


class _NoopStrategy(StrategyBase):
    def __init__(self, name: str = "noop") -> None:
        super().__init__(name=name)

    def on_init(self, ctx: StrategyContext) -> None:
        pass

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        entries = pd.Series(False, index=df.index)
        return entries, entries


def _config(method: str, enabled: bool = True, rebalance: int = 1) -> AppConfig:
    cfg = AppConfig()
    cfg.risk.portfolio_optimization.enabled = enabled
    cfg.risk.portfolio_optimization.method = method
    cfg.risk.portfolio_optimization.rebalance_every_n_bars = rebalance
    cfg.risk.portfolio_optimization.min_samples = 2
    return cfg


def _bar(symbol: str = "BTC/USDT", ts: int = 1, close: float = 100.0) -> Bar:
    return Bar(symbol=symbol, timestamp=ts, open=close, high=close, low=close, close=close, volume=1000.0)


class TestOptimizerSelection:
    def test_default_risk_parity(self) -> None:
        session = TradingSession(_config("risk_parity"), [_NoopStrategy()])
        assert isinstance(session._portfolio_optimizer, RiskParityOptimizer)

    def test_mean_variance_selected(self) -> None:
        session = TradingSession(_config("mean_variance"), [_NoopStrategy()])
        assert isinstance(session._portfolio_optimizer, MeanVarianceOptimizer)

    def test_disabled_returns_none(self) -> None:
        session = TradingSession(_config("risk_parity", enabled=False), [_NoopStrategy()])
        assert session._portfolio_optimizer is None


class TestAllocationMonitoring:
    @pytest.mark.asyncio
    async def test_rebalance_pushes_allocation_to_sink(self) -> None:
        """After a rebalance, the sink receives the computed weights."""
        session = TradingSession(
            _config("risk_parity"),
            [_NoopStrategy("s1"), _NoopStrategy("s2")],
        )
        sink = MagicMock()
        session._sink = sink  # type: ignore[assignment]
        session._running = True  # on_bar requires an active session
        # Seed per-strategy return histories so the optimizer has input.
        for sid in ("s1", "s2"):
            for i in range(10):
                session._portfolio.add_strategy_return(sid, 0.01 * (i % 2))
        # Rebalance triggers on bar_count % rebalance == 0; the first bar is
        # skipped (prev_equity NaN sentinel), so the second bar triggers.
        await session.on_bar(_bar(ts=1))
        await session.on_bar(_bar(ts=2))
        assert sink.record_portfolio_allocation.call_count == 1
        weights = sink.record_portfolio_allocation.call_args.args[0]
        assert set(weights) == {"s1", "s2"}
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    @pytest.mark.asyncio
    async def test_default_path_never_calls_sink(self) -> None:
        """enabled=False → optimizer None → no allocation monitoring calls."""
        session = TradingSession(
            _config("risk_parity", enabled=False),
            [_NoopStrategy("s1")],
        )
        sink = MagicMock()
        session._sink = sink  # type: ignore[assignment]
        session._running = True  # on_bar requires an active session
        await session.on_bar(_bar())
        sink.record_portfolio_allocation.assert_not_called()
