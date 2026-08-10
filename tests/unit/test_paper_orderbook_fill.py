"""W16: optional PaperGateway BBO fill model (default off)."""

from __future__ import annotations

import pytest

from quantflow.common.models import Order, OrderSide, OrderStatus
from quantflow.execution.paper_gateway import PaperGateway


@pytest.mark.asyncio
async def test_default_fill_uses_flat_slippage_not_bbo() -> None:
    """Default path: order price + slip; BBO ignored when disabled."""
    pg = PaperGateway({"slippage": 0.001, "taker_fee": 0.0})
    await pg.connect()
    pg.update_orderbook("BTC/USDT", bid=99.0, ask=101.0)
    order = Order(
        order_id="",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type="market",
        quantity=1.0,
        price=100.0,
    )
    await pg.send_order(order)
    assert order.status == OrderStatus.FILLED
    assert order.filled_price == pytest.approx(100.0 * 1.001)
    await pg.disconnect()


@pytest.mark.asyncio
async def test_orderbook_fill_buy_at_ask() -> None:
    pg = PaperGateway(
        {
            "orderbook_fill_enabled": True,
            "orderbook_fill": {"extra_slippage": 0.0},
            "taker_fee": 0.0,
            "slippage": 0.05,  # must not apply when BBO present
        }
    )
    await pg.connect()
    pg.update_orderbook("BTC/USDT", bid=100.0, ask=100.5)
    order = Order(
        order_id="",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type="market",
        quantity=1.0,
        price=100.0,
    )
    await pg.send_order(order)
    assert order.status == OrderStatus.FILLED
    assert order.filled_price == pytest.approx(100.5)
    await pg.disconnect()


@pytest.mark.asyncio
async def test_orderbook_fill_sell_at_bid() -> None:
    pg = PaperGateway(
        {
            "orderbook_fill_enabled": True,
            "orderbook_fill": {"extra_slippage": 0.0},
            "taker_fee": 0.0,
        }
    )
    await pg.connect()
    pg.update_orderbook("BTC/USDT", bid=99.5, ask=100.5)
    # seed long then sell
    buy = Order(
        order_id="",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type="market",
        quantity=1.0,
        price=100.0,
    )
    await pg.send_order(buy)
    sell = Order(
        order_id="",
        symbol="BTC/USDT",
        side=OrderSide.SELL,
        order_type="market",
        quantity=1.0,
        price=100.0,
    )
    await pg.send_order(sell)
    assert sell.filled_price == pytest.approx(99.5)
    await pg.disconnect()


@pytest.mark.asyncio
async def test_orderbook_enabled_without_bbo_falls_back() -> None:
    pg = PaperGateway(
        {
            "orderbook_fill_enabled": True,
            "slippage": 0.001,
            "taker_fee": 0.0,
        }
    )
    await pg.connect()
    order = Order(
        order_id="",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type="market",
        quantity=1.0,
        price=200.0,
    )
    await pg.send_order(order)
    assert order.filled_price == pytest.approx(200.0 * 1.001)
    await pg.disconnect()


def test_invalid_bbo_ignored() -> None:
    pg = PaperGateway({"orderbook_fill_enabled": True})
    pg.update_orderbook("BTC/USDT", bid=101.0, ask=100.0)  # crossed
    assert "BTC/USDT" not in pg._bbo
