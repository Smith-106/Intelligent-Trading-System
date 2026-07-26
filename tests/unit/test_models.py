"""Unit tests for common data models."""

import pytest

from quantflow.common.models import (
    Bar,
    Direction,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Portfolio,
    Position,
    RiskDecision,
    Signal,
)


class TestBar:
    def test_creation(self):
        bar = Bar(
            symbol="BTC/USDT",
            timestamp=1000,
            open=42000,
            high=42500,
            low=41800,
            close=42300,
            volume=1000,
        )
        assert bar.symbol == "BTC/USDT"
        assert bar.close == 42300

    def test_fields_required(self):
        with pytest.raises(TypeError):
            Bar(symbol="BTC/USDT")


class TestSignal:
    def test_creation(self):
        sig = Signal(
            strategy_id="test",
            symbol="BTC/USDT",
            direction=Direction.LONG,
            strength=0.8,
            price=42000,
            timestamp=1000,
        )
        assert sig.direction == Direction.LONG
        assert sig.strength == 0.8

    def test_default_strength(self):
        sig = Signal(symbol="X", direction=Direction.FLAT)
        assert sig.strength == 1.0
        assert sig.price == 0.0


class TestOrder:
    def test_creation(self):
        order = Order(
            order_id="o1",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.5,
        )
        assert order.status == OrderStatus.CREATED
        assert order.filled_quantity == 0.0

    def test_status_values(self):
        assert OrderStatus.CREATED.value == "created"
        assert OrderStatus.FILLED.value == "filled"


class TestDirection:
    def test_values(self):
        assert Direction.SHORT.value == -1
        assert Direction.FLAT.value == 0
        assert Direction.LONG.value == 1


class TestPosition:
    def test_market_value(self):
        pos = Position(symbol="BTC/USDT", quantity=0.5, entry_price=40000, current_price=42000)
        assert pos.market_value == 0.5 * 42000

    def test_unrealized_pnl(self):
        pos = Position(
            symbol="BTC/USDT",
            quantity=1.0,
            entry_price=40000,
            current_price=42000,
            unrealized_pnl=2000,
        )
        assert pos.unrealized_pnl == 2000

    def test_side_property(self):
        long_pos = Position(symbol="BTC/USDT", quantity=1.0, entry_price=40000, current_price=42000)
        assert long_pos.side == Direction.LONG
        short_pos = Position(
            symbol="BTC/USDT", quantity=-1.0, entry_price=40000, current_price=42000
        )
        assert short_pos.side == Direction.SHORT

    def test_with_current_price_long(self):
        """ISS-20260723-002: with_current_price is the single owner of the
        unrealized-PnL formula — (price - entry) * qty."""
        pos = Position(symbol="BTC/USDT", quantity=2.0, entry_price=40000, current_price=40000)
        updated = pos.with_current_price(45000)
        assert updated.current_price == 45000
        assert updated.unrealized_pnl == pytest.approx((45000 - 40000) * 2.0)
        # original unchanged
        assert pos.current_price == 40000

    def test_with_current_price_short(self):
        """Short position: unrealized PnL is negative when price rises."""
        pos = Position(symbol="BTC/USDT", quantity=-1.0, entry_price=40000, current_price=40000)
        updated = pos.with_current_price(41000)
        assert updated.unrealized_pnl == pytest.approx((41000 - 40000) * -1.0)

    def test_with_current_price_preserves_identity_fields(self):
        """with_current_price must not mutate symbol/qty/entry/strategy_id."""
        pos = Position(symbol="ETH/USDT", quantity=1.5, entry_price=3000, strategy_id="trend")
        updated = pos.with_current_price(3100)
        assert updated.symbol == "ETH/USDT"
        assert updated.quantity == 1.5
        assert updated.entry_price == 3000
        assert updated.strategy_id == "trend"


class TestPortfolio:
    def test_total_value(self):
        p = Portfolio(
            cash=50000,
            positions={
                "BTC/USDT": Position(
                    symbol="BTC/USDT", quantity=1.0, entry_price=40000, current_price=42000
                )
            },
        )
        assert p.total_value == 50000 + 42000

    def test_empty_portfolio(self):
        p = Portfolio(cash=100000)
        assert p.total_value == 100000
        assert len(p.positions) == 0


class TestRiskDecision:
    def test_passed(self):
        d = RiskDecision(passed=True)
        assert d.passed
        assert d.reason == ""

    def test_failed_with_reason(self):
        d = RiskDecision(passed=False, reason="drawdown_breach")
        assert not d.passed
        assert d.reason == "drawdown_breach"
