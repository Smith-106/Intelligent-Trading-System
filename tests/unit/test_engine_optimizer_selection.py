"""Tests for s5 follow-up: engine optimizer selection + allocation monitoring."""

from __future__ import annotations

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
    return Bar(
        symbol=symbol, timestamp=ts, open=close, high=close, low=close, close=close, volume=1000.0
    )


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


class TestSymbolLevelOptimization:
    def test_symbol_level_flag_stored(self) -> None:
        cfg = _config("risk_parity")
        cfg.risk.portfolio_optimization.level = "symbol"
        session = TradingSession(cfg, [_NoopStrategy()])
        assert session._portfolio_opt_level == "symbol"

    @pytest.mark.asyncio
    async def test_symbol_rebalance_sets_symbol_weights(self) -> None:
        cfg = _config("risk_parity", rebalance=1)
        cfg.risk.portfolio_optimization.level = "symbol"
        session = TradingSession(cfg, [_NoopStrategy("s1")])
        sink = MagicMock()
        session._sink = sink  # type: ignore[assignment]
        session._running = True
        # Seed per-symbol return histories so the optimizer has input.
        for sym in ("BTC/USDT", "ETH/USDT"):
            for i in range(10):
                session._portfolio.add_symbol_return(
                    sym, 0.01 * ((i + (1 if "ETH" in sym else 0)) % 3)
                )
        # First bar: prev_equity NaN skip; second unique ts triggers rebalance.
        await session.on_bar(_bar(symbol="BTC/USDT", ts=1, close=100.0))
        await session.on_bar(_bar(symbol="ETH/USDT", ts=2, close=50.0))
        assert sink.record_portfolio_allocation.call_count >= 1
        weights = session._portfolio.symbol_allocation
        assert set(weights) == {"BTC/USDT", "ETH/USDT"}
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    @pytest.mark.asyncio
    async def test_symbol_returns_from_close_not_only_positions(self) -> None:
        """Close-to-close returns accumulate for symbols with no position."""
        cfg = _config("risk_parity", rebalance=100)  # rebalance rarely
        cfg.risk.portfolio_optimization.level = "symbol"
        session = TradingSession(cfg, [_NoopStrategy("s1")])
        session._running = True
        # Two closes for ETH with no position — must still record a return.
        await session.on_bar(_bar(symbol="ETH/USDT", ts=1, close=100.0))
        await session.on_bar(_bar(symbol="ETH/USDT", ts=2, close=110.0))
        rets = session._portfolio.get_symbol_returns()
        assert "ETH/USDT" in rets
        assert len(rets["ETH/USDT"]) == 1
        assert abs(rets["ETH/USDT"][0] - 0.1) < 1e-9

    def test_get_allocation_for_signal_multiplies(self) -> None:
        from quantflow.signal.portfolio import PortfolioManager

        pm = PortfolioManager(initial_capital=100_000.0)
        pm.set_allocation({"trend_following": 1.0})
        pm.set_symbol_allocation({"BTC/USDT": 0.4, "ETH/USDT": 0.6})
        assert abs(pm.get_allocation_for_signal("trend_following", "BTC/USDT") - 0.4) < 1e-9
        assert abs(pm.get_allocation_for_signal("trend_following", "ETH/USDT") - 0.6) < 1e-9
        # Missing symbol → 0 when symbol map is active.
        assert pm.get_allocation_for_signal("trend_following", "SOL/USDT") == 0.0
        # Empty symbol map → strategy-only.
        pm.set_symbol_allocation({})
        assert abs(pm.get_allocation_for_signal("trend_following", "BTC/USDT") - 1.0) < 1e-9
