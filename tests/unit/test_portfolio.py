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
        # Full close attributes the closed leg's PnL to realized (Wave 1):
        # realized = (51000-50000)*1.0*1 = 1000
        assert pm.realized_pnl == 1000

    def test_update_position_applies_cash_and_fee(self):
        pm = PortfolioManager(100000)
        pm.update_position("BTC/USDT", 1.0, 50000, fee=50)

        assert pm.cash == 49950
        assert pm.total_value == 99950
        # Opening a position realizes nothing.
        assert pm.realized_pnl == 0

        pm.update_position("BTC/USDT", -0.4, 51000, fee=10)
        position = pm.get_position("BTC/USDT")

        assert position is not None
        assert pm.cash == 70340
        assert position.quantity == 0.6
        assert position.entry_price == 50000
        assert position.current_price == 51000
        # Partial close (long leg): realized = (51000-50000)*0.4*1 = 400.
        # Cash movement is unchanged vs prior semantics (conservative path).
        assert pm.realized_pnl == 400

    def test_total_value_respects_short_market_value(self):
        pm = PortfolioManager(100000)
        pm.update_position("BTC/USDT", -1.0, 50000)

        assert pm.total_value == 100000

        pm.mark_to_market({"BTC/USDT": 48000})
        assert pm.total_value == 102000

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
