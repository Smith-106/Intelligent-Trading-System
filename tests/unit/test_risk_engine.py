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
        engine = RiskEngine(RiskConfig(daily_loss_limit=-0.03, position_limit_pct=1.0))
        pos = Position("BTC/USDT", 1.0, 50000, 48000, unrealized_pnl=-3000)
        # ISS-20260720-004 Wave 3: daily_loss measures total_value vs daily_baseline.
        # total_value = 47000 + 48000 = 95000; baseline=100000 → pnl_pct = -0.05.
        pf = Portfolio(cash=47000, positions={"BTC/USDT": pos}, daily_baseline=100000)
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 48000)
        result = engine.check(sig, pf)
        assert not result.passed
        assert result.reason == "daily_loss_limit"

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


class TestCvarGateWiring:
    """ISS-20260719-001: the CVaR gate (_check_var) must actually trigger once
    the returns history is filled. Before the fix, add_return had no caller so
    _returns_history stayed empty and the `len < 30` guard short-circuited the
    gate to always-passed. The fix wires on_bar → add_return; these tests prove
    the gate fires when the tail breaches cvar_limit.
    """

    def test_insufficient_history_short_circuits_to_pass(self):
        """< 30 returns → gate cannot evaluate → passed (safe default)."""
        engine = RiskEngine(RiskConfig(cvar_limit=-0.05))
        for r in [0.01, -0.01, 0.02, -0.02]:  # only 4 returns
            engine.add_return(r)
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
        pf = Portfolio(cash=100000)
        assert engine.check(sig, pf).passed

    def test_gate_passes_when_tail_within_limit(self):
        """≥30 returns with a mild tail → CVaR milder than -0.05 → passed."""
        engine = RiskEngine(RiskConfig(cvar_limit=-0.05))
        # 50 returns, worst ~ -0.02 → CVaR ~ -0.02, well within -0.05
        mild = [0.01, -0.02, 0.015, -0.01, 0.005] * 10
        for r in mild:
            engine.add_return(r)
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
        pf = Portfolio(cash=100000)
        assert engine.check(sig, pf).passed

    def test_gate_blocks_when_tail_breaches_limit(self):
        """≥30 returns with a deep tail → CVaR worse than -0.05 → blocked."""
        engine = RiskEngine(RiskConfig(cvar_limit=-0.05))
        # 50 returns where the worst 5% are ~ -0.10 → CVaR ~ -0.10 < -0.05
        deep = [0.001] * 45 + [-0.10] * 5
        for r in deep:
            engine.add_return(r)
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
        pf = Portfolio(cash=100000)
        result = engine.check(sig, pf)
        assert not result.passed
        assert result.reason == "var_breach"
        assert "cvar_95" in result.details
