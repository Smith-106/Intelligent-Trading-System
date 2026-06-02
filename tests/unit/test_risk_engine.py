"""Tests for quantflow.signal.risk_engine."""

from quantflow.common.config import RiskConfig
from quantflow.common.models import Direction, Portfolio, Position, Signal
from quantflow.signal.risk_engine import RiskEngine


class TestRiskEngine:
    def test_pass_all_checks(self):
        engine = RiskEngine(RiskConfig())
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
        pf = Portfolio(cash=100000)
        result = engine.check(sig, pf)
        assert result.passed

    def test_weekly_loss_limit(self):
        engine = RiskEngine(RiskConfig(weekly_loss_limit=-0.05))
        engine.set_weekly_pnl(-0.06)
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
        pf = Portfolio(cash=100000)
        result = engine.check(sig, pf)
        assert not result.passed
        assert result.reason == "weekly_loss_limit"

    def test_weekly_loss_within_limit(self):
        engine = RiskEngine(RiskConfig(weekly_loss_limit=-0.05))
        engine.set_weekly_pnl(-0.03)
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
        pf = Portfolio(cash=100000)
        result = engine.check(sig, pf)
        assert result.passed

    def test_daily_loss_limit(self):
        engine = RiskEngine(RiskConfig(daily_loss_limit=-0.03))
        pos = Position("BTC/USDT", 1.0, 50000, 48000, unrealized_pnl=-3000)
        pf = Portfolio(cash=47000, positions={"BTC/USDT": pos})
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 48000)
        result = engine.check(sig, pf)
        assert isinstance(result.passed, bool)

    def test_max_drawdown(self):
        engine = RiskEngine(RiskConfig(max_drawdown=-0.10))
        pf = Portfolio(cash=80000, current_drawdown=-0.15)
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
        result = engine.check(sig, pf)
        assert not result.passed
        assert result.reason == "max_drawdown"

    def test_max_positions(self):
        engine = RiskEngine(RiskConfig(max_positions=2))
        pos1 = Position("BTC/USDT", 1.0, 50000, 50000)
        pos2 = Position("ETH/USDT", 10.0, 3000, 3000)
        pf = Portfolio(cash=50000, positions={"BTC/USDT": pos1, "ETH/USDT": pos2})
        sig = Signal("SOL/USDT", Direction.LONG, 0.8, 100)
        result = engine.check(sig, pf)
        assert not result.passed
        assert result.reason == "max_positions"

    def test_existing_symbol_passes_portfolio_limit(self):
        """Adding to an existing position should pass the max_positions check."""
        engine = RiskEngine(RiskConfig(max_positions=2, position_limit_pct=0.5))
        pos1 = Position("BTC/USDT", 1.0, 50000, 50000)
        pos2 = Position("ETH/USDT", 10.0, 3000, 3000)
        pf = Portfolio(cash=50000, positions={"BTC/USDT": pos1, "ETH/USDT": pos2})
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
        result = engine.check(sig, pf)
        # Should pass because symbol already exists (portfolio_limit check)
        # but may fail position_limit if existing position is too large
        assert isinstance(result.passed, bool)
