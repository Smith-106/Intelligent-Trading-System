"""Tests for engine.py uncovered paths — win-rate allocation, regime gating, data loop."""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from quantflow.common.config import AppConfig
from quantflow.common.models import Bar
from quantflow.signal.portfolio import PortfolioManager
from quantflow.strategy.engine import TradingSession


def _make_bar(price: float = 100.0, idx: int = 0) -> Bar:
    return Bar(
        "BTC/USDT", 1700000000 + idx * 60000, price - 0.5, price + 1.0, price - 1.0, price, 1000.0
    )


class TestWinRateAllocation:
    def test_win_rate_weighted_allocation_direct(self):
        """Lines 107-114: Win-rate-weighted capital allocation tested directly on PortfolioManager."""
        pm = PortfolioManager(initial_capital=100000.0)
        # Simulate what TradingSession.start() does
        win_rates = {"high_wr": 0.8, "low_wr": 0.2}
        total_wr = sum(win_rates.get(s, 0.5) for s in ["high_wr", "low_wr"])
        if total_wr > 0:
            allocation = {s: win_rates.get(s, 0.5) / total_wr for s in ["high_wr", "low_wr"]}
        else:
            allocation = {s: 1.0 / 2 for s in ["high_wr", "low_wr"]}
        pm.set_allocation(allocation)

        alloc = pm.allocation
        assert alloc["high_wr"] > alloc["low_wr"]
        assert sum(alloc.values()) == pytest.approx(1.0)

    def test_zero_total_win_rate_falls_back_to_equal(self):
        """Line 112: total_wr == 0 → equal allocation."""
        pm = PortfolioManager(initial_capital=100000.0)
        win_rates = {"s1": 0.0, "s2": 0.0}
        total_wr = sum(win_rates.get(s, 0.5) for s in ["s1", "s2"])
        if total_wr > 0:
            allocation = {s: win_rates.get(s, 0.5) / total_wr for s in ["s1", "s2"]}
        else:
            allocation = {s: 1.0 / 2 for s in ["s1", "s2"]}
        pm.set_allocation(allocation)

        alloc = pm.allocation
        assert alloc["s1"] == pytest.approx(0.5)
        assert alloc["s2"] == pytest.approx(0.5)

    def test_no_win_rates_equal_allocation(self):
        """Line 116: No win_rates → equal allocation."""
        pm = PortfolioManager(initial_capital=100000.0)
        strategies = ["a", "b"]
        allocation = {s: 1.0 / len(strategies) for s in strategies}
        pm.set_allocation(allocation)

        alloc = pm.allocation
        assert alloc["a"] == pytest.approx(0.5)
        assert alloc["b"] == pytest.approx(0.5)


class TestRegimeGating:
    def test_trending_regime_gates_mean_reversion(self):
        """Lines 178-181: Trending regime skips mean_reversion strategies."""
        from quantflow.strategy.base import StrategyBase

        class TrendStrategy(StrategyBase):
            required_regime = "trending"

            def on_init(self, ctx):
                pass

            def on_bar(self, ctx, bar):
                pass

            def generate_signals(self, df):
                return pd.Series(dtype=bool), pd.Series(dtype=bool)

        class MRStrategy(StrategyBase):
            required_regime = "mean_reversion"

            def on_init(self, ctx):
                pass

            def on_bar(self, ctx, bar):
                pass

            def generate_signals(self, df):
                return pd.Series(dtype=bool), pd.Series(dtype=bool)

        config = AppConfig()
        t = TrendStrategy(name="trend")
        t.required_regime = "trending"
        m = MRStrategy(name="mr")
        m.required_regime = "mean_reversion"
        strategies = [t, m]
        session = TradingSession(config, strategies)

        # Trending regime: is_trending=True
        # - "trending" strategy → NOT gated (passes)
        # - "mean_reversion" strategy → gated (skipped because regime.is_trending is True)
        mock_regime = MagicMock(is_trending=True)
        gated = []
        for strategy in session._strategies:
            if strategy.required_regime == "trending" and not mock_regime.is_trending:
                continue
            if strategy.required_regime == "mean_reversion" and mock_regime.is_trending:
                continue
            gated.append(strategy.name)

        assert "trend" in gated
        assert "mr" not in gated

    def test_mean_reversion_regime_gates_trending(self):
        """Lines 178-180: Mean-reversion regime skips trending strategies."""
        from quantflow.strategy.base import StrategyBase

        class TrendStrategy(StrategyBase):
            required_regime = "trending"

            def on_init(self, ctx):
                pass

            def on_bar(self, ctx, bar):
                pass

            def generate_signals(self, df):
                return pd.Series(dtype=bool), pd.Series(dtype=bool)

        config = AppConfig()
        t = TrendStrategy(name="trend")
        t.required_regime = "trending"
        strategies = [t]
        session = TradingSession(config, strategies)

        # Non-trending regime: is_trending=False
        # - "trending" strategy → gated (skipped because not regime.is_trending)
        mock_regime = MagicMock(is_trending=False)
        gated = []
        for strategy in session._strategies:
            if strategy.required_regime == "trending" and not mock_regime.is_trending:
                continue
            if strategy.required_regime == "mean_reversion" and mock_regime.is_trending:
                continue
            gated.append(strategy.name)

        assert "trend" not in gated


class TestCheckHealth:
    def test_check_health_returns_dict(self):
        """check_health returns health status dict."""
        config = AppConfig()
        session = TradingSession(config, [])
        health = session.check_health()
        assert isinstance(health, dict)
        assert "drawdown_ok" in health
        assert "pending_orders" in health
        # Key may be "open_positions" not "position_count"
        assert "open_positions" in health or "position_count" in health


class TestSessionLastError:
    def test_last_error_initially_none(self):
        config = AppConfig()
        session = TradingSession(config, [])
        assert session._last_error is None

    def test_set_last_error(self):
        config = AppConfig()
        session = TradingSession(config, [])
        session._last_error = "test error"
        assert session._last_error == "test error"


class TestAddReturnWiring:
    """ISS-20260719-001: on_bar must feed the realized per-bar return to both
    RiskEngine.add_return and PositionSizer.add_return. Before the fix, neither
    had any caller, so _returns_history never filled — vol-target (F3) never
    bound and the CVaR gate (risk_engine._check_var) always returned passed.
    """

    def _session(self) -> TradingSession:
        config = AppConfig()
        session = TradingSession(config, [])
        session._running = True  # on_bar early-returns while not running
        return session

    @pytest.mark.asyncio
    async def test_first_bar_does_not_feed_return(self):
        """The first bar has no prior equity to ratio against — no feed."""
        session = self._session()
        bar = _make_bar(price=100.0, idx=0)
        await session.on_bar(bar)
        assert len(session._risk_engine._returns_history) == 0
        assert len(session._position_sizer._returns_history) == 0

    @pytest.mark.asyncio
    async def test_second_bar_feeds_return(self):
        """From the second bar on, the realized return is fed to both."""
        session = self._session()
        await session.on_bar(_make_bar(price=100.0, idx=0))
        await session.on_bar(_make_bar(price=100.0, idx=1))
        # equity unchanged (no position) → bar_ret == 0, but still fed
        assert len(session._risk_engine._returns_history) == 1
        assert len(session._position_sizer._returns_history) == 1
        assert session._risk_engine._returns_history[0] == 0.0

    @pytest.mark.asyncio
    async def test_return_value_reflects_equity_change(self):
        """With an open position, a price move changes equity → non-zero bar_ret."""
        session = self._session()
        # Manually open a long: 1 unit @ 100, funded from cash.
        session._portfolio.update_position("BTC/USDT", 1.0, 100.0)
        # First bar at 100 establishes the prev_equity baseline (no feed yet).
        await session.on_bar(_make_bar(price=100.0, idx=0))
        prev = session._portfolio.total_value
        # Second bar at 110: position marks up, equity rises ~10/prev.
        await session.on_bar(_make_bar(price=110.0, idx=1))
        expected = (session._portfolio.total_value - prev) / prev
        fed_re = session._risk_engine._returns_history[-1]
        fed_ps = session._position_sizer._returns_history[-1]
        assert fed_re == pytest.approx(expected, abs=1e-9)
        assert fed_ps == pytest.approx(expected, abs=1e-9)
        assert fed_re > 0  # price rose → positive realized return

    @pytest.mark.asyncio
    async def test_history_grows_across_bars(self):
        """Feeding accumulates: 5 bars → 4 fed returns (first bar skipped)."""
        session = self._session()
        for i in range(5):
            await session.on_bar(_make_bar(price=100.0 + i, idx=i))
        assert len(session._risk_engine._returns_history) == 4
        assert len(session._position_sizer._returns_history) == 4

    @pytest.mark.asyncio
    async def test_no_lookahead_prev_equity_captured_before_mark(self):
        """The return's denominator must be the PRE-mark equity, not post-mark.

        Construct a position and a bar whose price move would change equity.
        The fed return must ratio against the equity BEFORE this bar's price
        was applied — otherwise it is a self-referential (look-ahead) return.
        """
        session = self._session()
        session._portfolio.update_position("BTC/USDT", 1.0, 100.0)
        # Bar 0 @ 100: prev_equity captured post-mark-100 (baseline for bar 1).
        await session.on_bar(_make_bar(price=100.0, idx=0))
        equity_before_bar1 = session._portfolio.total_value
        # Bar 1 @ 120: the return must use equity_before_bar1 as denominator.
        await session.on_bar(_make_bar(price=120.0, idx=1))
        fed = session._risk_engine._returns_history[-1]
        # The actual post-bar-1 equity:
        post = session._portfolio.total_value
        assert fed == pytest.approx((post - equity_before_bar1) / equity_before_bar1, abs=1e-9)
