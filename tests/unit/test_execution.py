"""Tests for quantflow.execution modules."""

import time
from typing import cast

import pytest

from quantflow.common.models import Order, OrderRequest, OrderResult, OrderSide, OrderStatus
from quantflow.execution.gateway_base import GatewayBase
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

    def test_track_terminal_result_and_local_orders(self):
        om = OrderManager()
        req = OrderRequest(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="limit",
            quantity=0.2,
            price=51000.0,
            strategy_id="terminal",
        )

        filled = om.track(req, OrderResult(order_id="filled-1", status=OrderStatus.FILLED))
        local = om.track(req)

        assert filled.status == OrderStatus.FILLED
        assert om.pending_count == 1
        assert local.order_id.startswith("local-")

    def test_update_unknown_order_and_query_helpers(self):
        om = OrderManager()
        req = OrderRequest(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=0.1,
            strategy_id="alpha",
        )
        res = OrderResult(order_id="oid-open", status=OrderStatus.SUBMITTED)
        om.track(req, res)
        om.track(
            OrderRequest(
                symbol="ETH/USDT",
                side=OrderSide.SELL,
                order_type="market",
                quantity=0.2,
                strategy_id="beta",
            ),
            OrderResult(order_id="oid-filled", status=OrderStatus.FILLED),
        )

        om.update("missing-order", OrderStatus.CANCELLED)

        open_orders = om.get_open_orders()
        alpha_orders = om.get_orders_by_strategy("alpha")
        missing_orders = om.get_orders_by_strategy("missing")

        assert [order.order_id for order in open_orders] == ["oid-open"]
        assert [order.order_id for order in alpha_orders] == ["oid-open"]
        assert missing_orders == []


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

    @pytest.mark.asyncio
    async def test_check_and_reason(self):
        pg = PaperGateway()
        await pg.connect()
        ks = KillSwitch(pg)

        assert ks.reason is None
        assert ks.check() == {"active": False, "reason": None}

        await ks.activate("risk_limit")

        assert ks.reason == "risk_limit"
        assert ks.check() == {"active": True, "reason": "risk_limit"}
        await pg.disconnect()

    @pytest.mark.asyncio
    async def test_activate_collects_gateway_errors(self):
        class FaultyGateway:
            async def cancel_all_orders(self):
                raise RuntimeError("cancel failed")

            async def query_positions(self):
                raise RuntimeError("query failed")

        ks = KillSwitch(cast(GatewayBase, FaultyGateway()))
        result = await ks.activate("faulty")

        assert result["status"] == "activated"
        assert "cancel_orders: cancel failed" in result["errors"]
        assert "query_positions: query failed" in result["errors"]

    @pytest.mark.asyncio
    async def test_activate_closes_short_position_and_records_close_errors(self):
        class Position:
            def __init__(self, symbol, quantity):
                self.symbol = symbol
                self.quantity = quantity

        class GatewayWithPositions:
            async def cancel_all_orders(self):
                return [True]

            async def query_positions(self):
                return [Position("BTC/USDT", -2.0), Position("ETH/USDT", 1.0)]

            async def send_order(self, order):
                if order.symbol == "ETH/USDT":
                    raise RuntimeError("close failed")
                return f"{order.symbol}-closed"

        ks = KillSwitch(cast(GatewayBase, GatewayWithPositions()))
        result = await ks.activate("positions")

        assert result["cancelled_orders"] == [True]
        assert result["closed_positions"] == [
            {"symbol": "BTC/USDT", "quantity": 2.0, "order_id": "BTC/USDT-closed"}
        ]
        assert "close_ETH/USDT: close failed" in result["errors"]

    @pytest.mark.asyncio
    async def test_activate_skips_zero_positions(self):
        class Position:
            def __init__(self, symbol, quantity):
                self.symbol = symbol
                self.quantity = quantity

        class GatewayWithFlatPosition:
            async def cancel_all_orders(self):
                return []

            async def query_positions(self):
                return [Position("BTC/USDT", 0.0)]

            async def send_order(self, order):
                raise AssertionError("flat position should not send orders")

        ks = KillSwitch(cast(GatewayBase, GatewayWithFlatPosition()))
        result = await ks.activate("flat")

        assert result["closed_positions"] == []
