"""Tests for quantflow.signal.portfolio."""

from quantflow.signal.portfolio import PortfolioManager


class TestPortfolioManager:
    def test_initial_state(self):
        pm = PortfolioManager(100000)
        assert pm.equity == 100000
        assert pm.current_drawdown == 0.0

    def test_update_position_new(self):
        pm = PortfolioManager(100000)
        pm.update_position("BTC/USDT", 1.0, 50000)
        assert "BTC/USDT" in pm.portfolio.positions

    def test_update_position_close(self):
        pm = PortfolioManager(100000)
        pm.update_position("BTC/USDT", 1.0, 50000)
        pm.update_position("BTC/USDT", -1.0, 51000)
        assert "BTC/USDT" not in pm.portfolio.positions

    def test_drawdown_tracking(self):
        pm = PortfolioManager(100000)
        pm.update_position("BTC/USDT", 1.0, 50000)
        pm.mark_to_market({"BTC/USDT": 40000})
        assert pm.current_drawdown <= 0

    def test_check_drawdown_pass(self):
        pm = PortfolioManager(100000)
        assert pm.check_drawdown(-0.10)

    def test_check_drawdown_breach(self):
        pm = PortfolioManager(100000)
        # Simulate drawdown by reducing cash and updating mark-to-market
        pm._cash = 80000
        pm.mark_to_market({})  # recalculate drawdown
        assert not pm.check_drawdown(-0.10)

    def test_set_allocation(self):
        pm = PortfolioManager(100000)
        pm.set_allocation({"trend": 0.6, "mean_rev": 0.4})
        assert pm.allocation.get("trend") == 0.6
        assert pm.allocation.get("unknown") is None

    def test_update_cash(self):
        pm = PortfolioManager(100000)
        pm.update_cash(-5000)
        assert pm.portfolio.cash == 95000

    def test_snapshot(self):
        pm = PortfolioManager(100000)
        snap = pm.snapshot()
        assert snap["equity"] == 100000
        assert snap["positions"] == 0

    def test_mark_to_market(self):
        pm = PortfolioManager(100000)
        pm.update_position("BTC/USDT", 1.0, 50000)
        pnl = pm.mark_to_market({"BTC/USDT": 52000})
        assert "BTC/USDT" in pnl
        assert pnl["BTC/USDT"] > 0
