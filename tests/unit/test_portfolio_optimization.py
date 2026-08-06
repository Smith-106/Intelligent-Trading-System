"""Tests for s5 portfolio-level features: per-strategy returns, budget utilization."""

from __future__ import annotations

from quantflow.common.models import Position
from quantflow.signal.portfolio import PortfolioManager


def _position(symbol: str, qty: float, price: float, strategy: str) -> Position:
    return Position(
        symbol=symbol,
        quantity=qty,
        entry_price=price,
        current_price=price,
        unrealized_pnl=0.0,
        strategy_id=strategy,
    )


class TestStrategyReturns:
    def test_add_and_get_strategy_returns(self) -> None:
        pm = PortfolioManager(initial_capital=100000.0)
        pm.add_strategy_return("trend", 0.01)
        pm.add_strategy_return("trend", -0.005)
        pm.add_strategy_return("momentum", 0.02)
        returns = pm.get_strategy_returns()
        assert returns["trend"] == [0.01, -0.005]
        assert returns["momentum"] == [0.02]

    def test_strategy_isolation(self) -> None:
        """One strategy's history must not pollute another's."""
        pm = PortfolioManager()
        pm.add_strategy_return("a", 0.1)
        pm.add_strategy_return("b", -0.1)
        assert pm.get_strategy_returns()["a"] == [0.1]
        assert pm.get_strategy_returns()["b"] == [-0.1]

    def test_window_bounds_history(self) -> None:
        pm = PortfolioManager()
        for i in range(10):
            pm.add_strategy_return("s", float(i), window=5)
        assert len(pm.get_strategy_returns()["s"]) == 5

    def test_empty_strategy_id_ignored(self) -> None:
        pm = PortfolioManager()
        pm.add_strategy_return("", 0.01)
        assert pm.get_strategy_returns() == {}

    def test_default_path_no_returns(self) -> None:
        pm = PortfolioManager()
        assert pm.get_strategy_returns() == {}


class TestBudgetUtilization:
    def test_report_shape(self) -> None:
        pm = PortfolioManager(initial_capital=100000.0)
        pm.set_allocation({"trend": 0.5, "momentum": 0.5})
        pm.set_position("BTC/USDT", _position("BTC/USDT", 1.0, 30000.0, "trend"))
        report = pm.budget_utilization()
        assert set(report) == {"trend", "momentum"}
        trend = report["trend"]
        # total_value = cash 100000 + position 30000 = 130000.
        assert abs(trend["allocated_notional"] - 65000.0) < 1e-6
        assert trend["exposure_notional"] == 30000.0
        assert abs(trend["utilization_pct"] - 30000.0 / 65000.0) < 1e-9

    def test_compound_strategy_exposure_attributed(self) -> None:
        pm = PortfolioManager(initial_capital=100000.0)
        pm.set_allocation({"trend": 0.5, "momentum": 0.5})
        pm.set_position("BTC/USDT", _position("BTC/USDT", 1.0, 20000.0, "trend,momentum"))
        report = pm.budget_utilization()
        # Constituent split: each gets the full position value.
        assert report["trend"]["exposure_notional"] == 20000.0
        assert report["momentum"]["exposure_notional"] == 20000.0

    def test_zero_weight_budget(self) -> None:
        pm = PortfolioManager(initial_capital=100000.0)
        pm.set_allocation({"unfunded": 0.0})
        pm.set_position("X", _position("X", 1.0, 100.0, "unfunded"))
        report = pm.budget_utilization()
        assert report["unfunded"]["utilization_pct"] == 0.0


class TestDynamicAllocation:
    def test_set_allocation_updates(self) -> None:
        pm = PortfolioManager()
        pm.set_allocation({"a": 0.5, "b": 0.5})
        assert pm.get_strategy_allocation("a") == 0.5
        pm.set_allocation({"a": 0.9, "b": 0.1})
        assert pm.get_strategy_allocation("a") == 0.9

    def test_set_allocation_copies(self) -> None:
        """set_allocation must not alias the caller's dict (rebalance reuse)."""
        pm = PortfolioManager()
        src = {"a": 0.5}
        pm.set_allocation(src)
        src["a"] = 1.0
        assert pm.get_strategy_allocation("a") == 0.5
