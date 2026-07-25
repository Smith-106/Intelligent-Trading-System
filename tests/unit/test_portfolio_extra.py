"""Tests for portfolio.py uncovered paths — quantity_delta≈0, mark-to-market."""

from __future__ import annotations

import pytest

from quantflow.signal.portfolio import PortfolioManager


class TestPortfolioQuantityDeltaZero:
    def test_zero_delta_no_existing_position(self):
        """Lines 85-87: quantity_delta≈0 with no existing position → just refresh drawdown."""
        pm = PortfolioManager(initial_capital=100000.0)
        # update_position with tiny delta and no existing position
        pm.update_position("BTC/USDT", 0.0, 50000.0)
        # No position should be created
        assert "BTC/USDT" not in pm._positions
        # Cash unchanged
        assert pm.cash == pytest.approx(100000.0)

    def test_zero_delta_with_existing_position_updates_price(self):
        """Lines 88-97: quantity_delta≈0 with existing position → mark-to-market."""
        pm = PortfolioManager(initial_capital=100000.0)
        # Create a position first
        pm.update_position("BTC/USDT", 1.0, 50000.0)
        pos = pm._positions["BTC/USDT"]
        assert pos.quantity == pytest.approx(1.0)
        assert pos.entry_price == pytest.approx(50000.0)

        # Now update with zero delta but new price → mark-to-market
        pm.update_position("BTC/USDT", 0.0, 55000.0)
        pos = pm._positions["BTC/USDT"]
        assert pos.quantity == pytest.approx(1.0)
        assert pos.entry_price == pytest.approx(50000.0)  # entry unchanged
        assert pos.current_price == pytest.approx(55000.0)
        assert pos.unrealized_pnl == pytest.approx(5000.0)

    def test_very_small_delta_treated_as_zero(self):
        """abs(quantity_delta) < 1e-10 is treated as zero."""
        pm = PortfolioManager(initial_capital=100000.0)
        pm.update_position("BTC/USDT", 1.0, 50000.0)
        # Delta of 1e-11 is below threshold
        pm.update_position("BTC/USDT", 1e-11, 52000.0)
        pos = pm._positions["BTC/USDT"]
        assert pos.current_price == pytest.approx(52000.0)
        assert pos.quantity == pytest.approx(1.0)  # not 1.00000000001

    def test_zero_delta_refreshes_drawdown(self):
        """Calling update_position with zero delta triggers _refresh_drawdown."""
        pm = PortfolioManager(initial_capital=100000.0)
        # Create position first, then do a zero-delta update
        pm.update_position("BTC/USDT", 1.0, 50000.0)
        # Zero-delta update with lower price → drawdown should change
        pm.update_position("BTC/USDT", 0.0, 40000.0)
        # Drawdown should now reflect the price drop
        assert pm.current_drawdown < 0


class TestPortfolioAllocation:
    def test_set_allocation(self):
        """set_allocation sets per-symbol weight."""
        pm = PortfolioManager(initial_capital=100000.0)
        pm.set_allocation({"trend_following": 0.6, "mean_reversion": 0.4})
        assert pm._allocation["trend_following"] == pytest.approx(0.6)
        assert pm._allocation["mean_reversion"] == pytest.approx(0.4)

    def test_update_market_prices(self):
        """update_market_prices updates current_price on all matching positions."""
        pm = PortfolioManager(initial_capital=100000.0)
        pm.update_position("BTC/USDT", 1.0, 50000.0)
        pm.update_market_prices({"BTC/USDT": 55000.0})
        pos = pm._positions["BTC/USDT"]
        assert pos.current_price == pytest.approx(55000.0)

    def test_total_value_with_positions(self):
        """total_value = cash + sum of unrealized PnL."""
        pm = PortfolioManager(initial_capital=100000.0)
        pm.update_position("BTC/USDT", 1.0, 50000.0)
        # Cash = 100000 - 50000 = 50000, unrealized = 0 at entry
        assert pm.total_value == pytest.approx(100000.0)
        # Price goes up
        pm.update_market_prices({"BTC/USDT": 55000.0})
        assert pm.total_value == pytest.approx(105000.0)

    def test_check_drawdown_within_limit(self):
        """check_drawdown returns True when within limit."""
        pm = PortfolioManager(initial_capital=100000.0)
        # Default drawdown is 0.0, max_drawdown is negative (-0.10)
        # 0.0 > -0.10 → within limit
        assert pm.check_drawdown(-0.10) is True

    def test_close_position_removes_from_dict(self):
        """Closing a position removes it from _positions."""
        pm = PortfolioManager(initial_capital=100000.0)
        pm.update_position("BTC/USDT", 1.0, 50000.0)
        assert "BTC/USDT" in pm._positions
        # Close by selling all
        pm.update_position("BTC/USDT", -1.0, 55000.0)
        assert "BTC/USDT" not in pm._positions

    def test_update_cash(self):
        """update_cash adjusts cash balance."""
        pm = PortfolioManager(initial_capital=100000.0)
        pm.update_cash(5000.0)
        assert pm.cash == pytest.approx(105000.0)
        pm.update_cash(-3000.0)
        assert pm.cash == pytest.approx(102000.0)


class TestPortfolioRealizedAttribution:
    """ISS-20260720-004 Wave 1 — realized PnL attribution on flip/partial-close.

    Realized is attributed independently of cash. Cash movement follows the
    prior single-line notional semantics (conservative path), so existing
    cash assertions hold; the new ``realized_pnl`` accumulator makes the
    closed leg's PnL observable.
    """

    def test_realized_pnl_on_flip_long_to_short(self):
        """Flip long 1.0 → short 1.0 via sell 2.0 attributes the long leg's
        close PnL to realized. New short leg entry is the fill price."""
        pm = PortfolioManager(initial_capital=100000.0)
        pm.update_position("BTC/USDT", 1.0, 50000.0)
        # cash = 100000 - 50000 = 50000
        assert pm.cash == pytest.approx(50000.0)
        assert pm.realized_pnl == pytest.approx(0.0)

        pm.update_position("BTC/USDT", -2.0, 51000.0)
        # cash -= (-2.0)*51000 = +102000 → 152000 (notional semantics unchanged)
        assert pm.cash == pytest.approx(152000.0)
        # realized = (51000-50000)*1.0*1 = 1000 (long leg closed at +1000)
        assert pm.realized_pnl == pytest.approx(1000.0)
        pos = pm.get_position("BTC/USDT")
        assert pos is not None
        assert pos.quantity == pytest.approx(-1.0)  # new short 1.0
        assert pos.entry_price == pytest.approx(51000.0)  # flip → fill price
        # total_value = cash + short market_value = 152000 - 51000 = 101000
        assert pm.total_value == pytest.approx(101000.0)

    def test_realized_pnl_on_flip_short_to_long(self):
        """Flip short 1.0 → long 1.0 via buy 2.0 attributes the short leg's
        close PnL to realized (entry-price, short sign)."""
        pm = PortfolioManager(initial_capital=100000.0)
        pm.update_position("BTC/USDT", -1.0, 50000.0)
        # cash += 50000 → 150000 (short open receives cash)
        assert pm.cash == pytest.approx(150000.0)
        assert pm.realized_pnl == pytest.approx(0.0)

        pm.update_position("BTC/USDT", 2.0, 49000.0)
        # cash -= 2.0*49000 = 98000 → 52000
        assert pm.cash == pytest.approx(52000.0)
        # realized = (49000-50000)*1.0*(-1) = 1000 (short leg closed at +1000)
        assert pm.realized_pnl == pytest.approx(1000.0)
        pos = pm.get_position("BTC/USDT")
        assert pos is not None
        assert pos.quantity == pytest.approx(1.0)  # new long 1.0
        assert pos.entry_price == pytest.approx(49000.0)  # flip → fill price
        # total_value = cash + long market_value = 52000 + 49000 = 101000
        assert pm.total_value == pytest.approx(101000.0)

    def test_snapshot_exposes_realized_pnl(self):
        """snapshot() exposes realized_pnl for web/observability."""
        pm = PortfolioManager(initial_capital=100000.0)
        assert pm.snapshot()["realized_pnl"] == pytest.approx(0.0)
        pm.update_position("BTC/USDT", 1.0, 50000.0)
        pm.update_position("BTC/USDT", -1.0, 52000.0)
        assert pm.snapshot()["realized_pnl"] == pytest.approx(2000.0)

    def test_portfolio_snapshot_carries_realized_and_baseline(self):
        """The Portfolio model snapshot carries realized_pnl + daily_baseline
        so RiskEngine.check (pure function) reads them without holding an L4
        reference."""
        pm = PortfolioManager(initial_capital=100000.0)
        pm.update_position("BTC/USDT", 1.0, 50000.0)
        pm.update_position("BTC/USDT", -0.5, 51000.0)
        snap = pm.portfolio
        assert snap.realized_pnl == pytest.approx(500.0)
        # daily_baseline defaults to NaN until Wave 3 anchors it.
        import math

        assert math.isnan(snap.daily_baseline)
