"""Additional branch coverage tests for paper gateway and position manager."""

from __future__ import annotations

import pytest

from quantflow.common.models import Order, OrderSide
from quantflow.execution.paper_gateway import PaperGateway
from quantflow.execution.position_manager import PositionManager


class TestPositionManagerExtra:
    def test_zero_delta_is_noop_and_getters_cover_remaining_paths(self) -> None:
        manager = PositionManager()

        manager.update_position("BTC/USDT", 0.0, 100.0)

        assert manager.get_position("BTC/USDT") is None
        assert manager.get_all_positions() == []
        assert manager.close_position("BTC/USDT") is None
        assert manager.total_unrealized_pnl == 0.0
        assert manager.total_market_value == 0.0

    def test_same_direction_increase_and_reduce_preserve_expected_entry_price(self) -> None:
        manager = PositionManager()
        manager.update_position("BTC/USDT", 1.0, 100.0)
        manager.update_position("BTC/USDT", 1.0, 120.0)

        pos = manager.get_position("BTC/USDT")
        assert pos is not None
        assert pos.quantity == 2.0
        assert pos.entry_price == pytest.approx(110.0)

        manager.update_position("BTC/USDT", -0.5, 130.0)
        pos = manager.get_position("BTC/USDT")
        assert pos is not None
        assert pos.quantity == 1.5
        assert pos.entry_price == pytest.approx(110.0)

    def test_short_position_increase_and_close_position_branch(self) -> None:
        manager = PositionManager()
        manager.update_position("ETH/USDT", -1.0, 200.0)
        manager.update_position("ETH/USDT", -2.0, 180.0)

        pos = manager.get_position("ETH/USDT")
        assert pos is not None
        assert pos.quantity == -3.0
        assert pos.entry_price == pytest.approx((200.0 + 360.0) / 3.0)

        closed = manager.close_position("ETH/USDT")
        assert closed is not None
        assert closed.quantity == -3.0
        assert manager.get_position("ETH/USDT") is None


class TestPaperGatewayExtra:
    @pytest.mark.asyncio
    async def test_cancel_order_and_is_connected(self) -> None:
        gateway = PaperGateway()

        assert gateway.is_connected is True
        assert await gateway.cancel_order("oid-1", "BTC/USDT") is True
        assert await gateway.cancel_all_orders() == []

    @pytest.mark.asyncio
    async def test_update_price_refreshes_existing_position_and_equity(self) -> None:
        gateway = PaperGateway()
        await gateway.connect()
        order = Order(
            order_id="",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=2.0,
            price=100.0,
        )
        await gateway.send_order(order)

        gateway.update_market_price("BTC/USDT", 130.0)
        positions = await gateway.query_positions()

        assert positions[0].current_price == 130.0
        assert positions[0].unrealized_pnl > 0
        assert gateway._equity() > 0

    def test_update_position_covers_zero_open_close_and_average_paths(self) -> None:
        gateway = PaperGateway()

        gateway._update_position("BTC/USDT", 0.0, 100.0)
        assert gateway._positions == {}

        gateway._update_position("BTC/USDT", 1.0, 100.0)
        gateway._update_position("BTC/USDT", 1.0, 120.0)
        pos = gateway._positions["BTC/USDT"]
        assert pos.quantity == 2.0
        assert pos.entry_price == pytest.approx(110.0)

        gateway._update_position("BTC/USDT", -2.0, 110.0)
        assert "BTC/USDT" not in gateway._positions

        gateway._update_position("ETH/USDT", -1.0, 200.0)
        gateway._update_position("ETH/USDT", 0.5, 190.0)
        pos = gateway._positions["ETH/USDT"]
        assert pos.quantity == -0.5
        assert pos.entry_price == pytest.approx(200.0)
