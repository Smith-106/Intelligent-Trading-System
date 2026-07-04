"""Tests for RiskEngine._check_strategy_budget — P0-4."""

from __future__ import annotations

from quantflow.common.config import RiskConfig
from quantflow.common.models import Direction, Portfolio, Position, Signal
from quantflow.signal.risk_engine import RiskEngine


class TestStrategyBudgetFilter:
    def _signal(self, strategy_id: str = "s1", symbol: str = "BTC/USDT") -> Signal:
        return Signal(
            symbol=symbol,
            direction=Direction.LONG,
            strength=0.8,
            price=100.0,
            strategy_id=strategy_id,
        )

    def test_no_budget_config_passes(self):
        """Without strategy_risk_budgets, strategy budget check always passes."""
        engine = RiskEngine(RiskConfig())
        portfolio = Portfolio(cash=100000.0)
        result = engine.check(self._signal("s1"), portfolio)
        assert result.passed

    def test_signal_strategy_not_in_budget_passes(self):
        """When signal.strategy_id is not in budget dict, check passes."""
        budgets = {"s1": 0.3, "s2": 0.3}
        engine = RiskEngine(RiskConfig(), strategy_risk_budgets=budgets)
        portfolio = Portfolio(cash=100000.0)
        result = engine.check(self._signal("s3"), portfolio)
        assert result.passed

    def test_within_budget_passes(self):
        """Strategy exposure below budget limit passes."""
        budgets = {"s1": 0.5}
        engine = RiskEngine(RiskConfig(position_limit_pct=1.0), strategy_risk_budgets=budgets)
        pos = Position("BTC/USDT", 1.0, 50000.0, 50000.0, strategy_id="s1")
        portfolio = Portfolio(cash=100000.0, positions={"BTC/USDT": pos})
        # s1 exposure = 50000, budget = 150000 * 0.5 = 75000 → passes
        result = engine.check(self._signal("s1"), portfolio)
        assert result.passed

    def test_at_budget_limit_fails(self):
        """Strategy exposure >= budget limit fails."""
        budgets = {"s1": 0.2}
        engine = RiskEngine(RiskConfig(position_limit_pct=1.0), strategy_risk_budgets=budgets)
        pos = Position("BTC/USDT", 1.0, 50000.0, 50000.0, strategy_id="s1")
        portfolio = Portfolio(cash=100000.0, positions={"BTC/USDT": pos})
        # s1 exposure = 50000, total_value = 150000, budget = 150000 * 0.2 = 30000 → fails
        result = engine.check(self._signal("s1"), portfolio)
        assert result.passed is False
        assert result.reason == "strategy_budget"
        assert result.details["strategy_id"] == "s1"
        assert result.details["budget_pct"] == 0.2

    def test_only_same_strategy_id_positions_counted(self):
        """Positions with different strategy_id should NOT be counted."""
        budgets = {"s1": 0.2}
        engine = RiskEngine(RiskConfig(position_limit_pct=1.0), strategy_risk_budgets=budgets)
        pos_s1 = Position("BTC/USDT", 1.0, 50000.0, 50000.0, strategy_id="s1")
        pos_s2 = Position("ETH/USDT", 10.0, 3000.0, 3000.0, strategy_id="s2")
        portfolio = Portfolio(
            cash=100000.0,
            positions={"BTC/USDT": pos_s1, "ETH/USDT": pos_s2},
        )
        # s1 exposure = 50000, total_value = 180000, budget = 180000 * 0.2 = 36000 → fails
        result = engine.check(self._signal("s1"), portfolio)
        assert result.passed is False
        assert result.reason == "strategy_budget"
        assert result.details["exposure"] == 50000.0  # only s1 positions

    def test_zero_current_price_position_contributes_zero(self):
        """Positions with current_price=0 should contribute 0 to exposure."""
        budgets = {"s1": 0.1}
        engine = RiskEngine(RiskConfig(position_limit_pct=1.0), strategy_risk_budgets=budgets)
        pos = Position("BTC/USDT", 1.0, 50000.0, 0.0, strategy_id="s1")
        portfolio = Portfolio(cash=100000.0, positions={"BTC/USDT": pos})
        # s1 exposure = 0 (current_price=0), budget = 100000 * 0.1 = 10000 → passes
        result = engine.check(self._signal("s1"), portfolio)
        assert result.passed

    def test_zero_total_value_passes(self):
        """When total_value=0, budget check passes (avoids div-by-zero)."""
        budgets = {"s1": 0.3}
        engine = RiskEngine(RiskConfig(), strategy_risk_budgets=budgets)
        pos = Position("BTC/USDT", 1.0, 0.0, 0.0, strategy_id="s1")
        portfolio = Portfolio(cash=0.0, positions={"BTC/USDT": pos})
        result = engine.check(self._signal("s1"), portfolio)
        assert result.passed

    def test_multiple_positions_same_strategy(self):
        """Multiple positions with same strategy_id should sum."""
        budgets = {"s1": 0.15}
        engine = RiskEngine(RiskConfig(position_limit_pct=1.0), strategy_risk_budgets=budgets)
        pos1 = Position("BTC/USDT", 1.0, 50000.0, 50000.0, strategy_id="s1")
        pos2 = Position("ETH/USDT", 5.0, 3000.0, 3000.0, strategy_id="s1")
        portfolio = Portfolio(
            cash=100000.0,
            positions={"BTC/USDT": pos1, "ETH/USDT": pos2},
        )
        # s1 exposure = 50000 + 15000 = 65000, total = 165000, budget = 165000 * 0.15 = 24750 → fails
        result = engine.check(self._signal("s1"), portfolio)
        assert result.passed is False
        assert result.reason == "strategy_budget"
        assert result.details["exposure"] == 65000.0

    def test_empty_strategy_id_not_in_budget_passes(self):
        """Signal with empty strategy_id should pass when not in budget dict."""
        budgets = {"s1": 0.3}
        engine = RiskEngine(RiskConfig(), strategy_risk_budgets=budgets)
        portfolio = Portfolio(cash=100000.0)
        result = engine.check(self._signal(""), portfolio)
        assert result.passed

    def test_strategy_budget_details_include_all_fields(self):
        """Failed strategy_budget decision should include all detail fields."""
        budgets = {"s1": 0.1}
        engine = RiskEngine(RiskConfig(position_limit_pct=1.0), strategy_risk_budgets=budgets)
        pos = Position("BTC/USDT", 1.0, 50000.0, 50000.0, strategy_id="s1")
        portfolio = Portfolio(cash=100000.0, positions={"BTC/USDT": pos})
        result = engine.check(self._signal("s1"), portfolio)
        assert not result.passed
        assert "strategy_id" in result.details
        assert "exposure" in result.details
        assert "budget" in result.details
        assert "budget_pct" in result.details
