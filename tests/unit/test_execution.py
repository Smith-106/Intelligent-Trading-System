"""Tests for quantflow.execution modules."""

import time

import pytest

from quantflow.common.models import Order, OrderRequest, OrderResult, OrderSide, OrderStatus
from quantflow.execution.kill_switch import KillSwitch
from quantflow.execution.order_manager import OrderManager
from quantflow.execution.paper_gateway import PaperGateway
from quantflow.execution.position_manager import PositionManager


class TestOrderManager:
    def test_track_order(self):
        om = OrderManager()
        req = OrderRequest(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=0.1,
            price=50000,
            strategy_id="test",
        )
        res = OrderResult(order_id="test-1", status=OrderStatus.SUBMITTED)
        om.track(req, res)
        assert om.total_orders == 1
        assert om.pending_count == 1

    def test_update_order(self):
        om = OrderManager()
        req = OrderRequest(symbol="BTC/USDT", side=OrderSide.BUY, order_type="market", quantity=0.1)
        res = OrderResult(order_id="oid-1", status=OrderStatus.SUBMITTED)
        om.track(req, res)
        om.update("oid-1", OrderStatus.FILLED, filled_quantity=0.1, filled_price=50000)
        assert om.pending_count == 0
        order = om.get_order("oid-1")
        assert order is not None
        assert order.status == OrderStatus.FILLED

    def test_check_timeouts(self):
        om = OrderManager(timeout=0)
        req = OrderRequest(symbol="BTC/USDT", side=OrderSide.BUY, order_type="market", quantity=0.1)
        res = OrderResult(order_id="oid-2", status=OrderStatus.SUBMITTED)
        om.track(req, res)
        time.sleep(0.01)
        timed_out = om.check_timeouts()
        assert len(timed_out) > 0


class TestPositionManager:
    def test_open_position(self):
        pm = PositionManager()
        pm.update_position("BTC/USDT", 1.0, 50000)
        assert pm.has_position("BTC/USDT")
        pos = pm.get_position("BTC/USDT")
        assert pos.quantity == 1.0

    def test_close_position(self):
        pm = PositionManager()
        pm.update_position("BTC/USDT", 1.0, 50000)
        pm.update_position("BTC/USDT", -1.0, 51000)
        assert not pm.has_position("BTC/USDT")

    def test_update_market_price(self):
        pm = PositionManager()
        pm.update_position("BTC/USDT", 1.0, 50000)
        pm.update_market_price("BTC/USDT", 52000)
        pos = pm.get_position("BTC/USDT")
        assert pos.current_price == 52000

    def test_total_unrealized_pnl(self):
        pm = PositionManager()
        pm.update_position("BTC/USDT", 1.0, 50000)
        pm.update_market_price("BTC/USDT", 52000)
        pos = pm.get_position("BTC/USDT")
        assert pos is not None
        assert pos.current_price == 52000
        assert pos.unrealized_pnl == pytest.approx(2000.0)


class TestPaperGateway:
    @pytest.mark.asyncio
    async def test_connect_and_order(self):
        pg = PaperGateway()
        await pg.connect()
        order = Order(
            order_id="",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=0.1,
            price=50000,
        )
        await pg.send_order(order)
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == 0.1
        await pg.disconnect()

    @pytest.mark.asyncio
    async def test_sell_order(self):
        pg = PaperGateway()
        await pg.connect()
        buy_order = Order(
            order_id="",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=1.0,
            price=50000,
        )
        await pg.send_order(buy_order)
        sell_order = Order(
            order_id="",
            symbol="BTC/USDT",
            side=OrderSide.SELL,
            order_type="market",
            quantity=0.5,
            price=51000,
        )
        await pg.send_order(sell_order)
        assert sell_order.status == OrderStatus.FILLED
        await pg.disconnect()

    @pytest.mark.asyncio
    async def test_query_positions(self):
        pg = PaperGateway()
        await pg.connect()
        order = Order(
            order_id="",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=1.0,
            price=50000,
        )
        await pg.send_order(order)
        positions = await pg.query_positions()
        assert len(positions) > 0
        await pg.disconnect()

    @pytest.mark.asyncio
    async def test_rejected_no_price(self):
        pg = PaperGateway()
        await pg.connect()
        order = Order(
            order_id="",
            symbol="UNKNOWN/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=1.0,
            price=None,
        )
        await pg.send_order(order)
        assert order.status == OrderStatus.REJECTED
        await pg.disconnect()


class TestKillSwitch:
    @pytest.mark.asyncio
    async def test_activate(self):
        pg = PaperGateway()
        await pg.connect()
        ks = KillSwitch(pg)
        result = await ks.activate("test_activation")
        assert ks.is_active
        assert result["status"] == "activated"
        await pg.disconnect()

    @pytest.mark.asyncio
    async def test_deactivate(self):
        pg = PaperGateway()
        await pg.connect()
        ks = KillSwitch(pg)
        await ks.activate("test")
        ks.deactivate()
        assert not ks.is_active
        await pg.disconnect()

    @pytest.mark.asyncio
    async def test_double_activate(self):
        pg = PaperGateway()
        await pg.connect()
        ks = KillSwitch(pg)
        await ks.activate("first")
        result = await ks.activate("second")
        assert result["status"] == "already_active"
        await pg.disconnect()
