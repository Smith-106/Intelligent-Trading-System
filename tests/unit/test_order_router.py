"""ISS-20260723-003 — OrderRouter unit tests.

OrderRouter was extracted from ExecutionEngine (god-object retirement). It
owns gateway dispatch + Order/Request construction; these tests cover the
three concerns in isolation, independent of the submit orchestration.
"""

from __future__ import annotations

import pytest

from quantflow.common.models import Order, OrderRequest, OrderSide, Position
from quantflow.execution.gateway_base import GatewayBase, GatewayError
from quantflow.execution.order_router import OrderRouter


class _RecordingGateway(GatewayBase):
    """Minimal gateway that records the dispatched order + its return id."""

    def __init__(self, return_id: str = "exch-1", raise_error: BaseException | None = None) -> None:
        self._return_id = return_id
        self._raise = raise_error
        self.dispatched: list[Order] = []

    async def connect(self, config=None) -> None:
        return None

    async def send_order(self, order: Order) -> str:
        self.dispatched.append(order)
        if self._raise is not None:
            raise self._raise
        return self._return_id

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        return True

    async def query_positions(self):
        return []

    async def query_open_orders(self, symbol: str) -> list:
        return []


# ---------------------------------------------------------------------------
# route — gateway dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_dispatches_order_and_returns_exchange_id() -> None:
    """ISS-20260723-003: route() forwards the order to gateway.send_order and
    returns the exchange-assigned id."""
    gateway = _RecordingGateway(return_id="okx-999")
    router = OrderRouter(gateway)
    order = Order(
        order_id="",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type="market",
        quantity=0.1,
    )

    result = await router.route(order)

    assert result == "okx-999"
    assert gateway.dispatched == [order]


@pytest.mark.asyncio
async def test_route_raises_when_no_gateway_bound() -> None:
    """ISS-20260723-003: arch-017 lazy binding — an unbound router raises the
    same 'call start() first' contract ExecutionEngine.submit enforced inline."""
    router = OrderRouter()  # no gateway
    order = Order(
        order_id="",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type="market",
        quantity=0.1,
    )

    with pytest.raises(RuntimeError, match="Gateway not initialized"):
        await router.route(order)


@pytest.mark.asyncio
async def test_route_propagates_gateway_errors() -> None:
    """ISS-20260723-003: a gateway send_order failure surfaces unchanged so
    ExecutionEngine.submit's except branch can redact + mark REJECTED."""
    gateway = _RecordingGateway(raise_error=GatewayError("create_order failed"))
    router = OrderRouter(gateway)
    order = Order(
        order_id="",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type="market",
        quantity=0.1,
    )

    with pytest.raises(GatewayError, match="create_order failed"):
        await router.route(order)


def test_set_gateway_rebinds_after_construction() -> None:
    """ISS-20260723-003: arch-017 — set_gateway rebinds the gateway the engine
    builds in start() after the router was constructed unbound."""
    router = OrderRouter()
    assert router.gateway is None

    gateway = _RecordingGateway()
    router.set_gateway(gateway)

    assert router.gateway is gateway


# ---------------------------------------------------------------------------
# build_order — OrderRequest → Order construction
# ---------------------------------------------------------------------------


def test_build_order_copies_request_fields_and_params() -> None:
    """ISS-20260723-003: build_order is a pure transformation; params is
    copied so downstream order.params writes do not mutate the caller's request."""
    router = OrderRouter()
    request = OrderRequest(
        symbol="ETH/USDT",
        side=OrderSide.SELL,
        order_type="limit",
        quantity=1.0,
        price=3000.0,
        strategy_id="strat-x",
        params={"reduceOnly": True},
    )

    order = router.build_order(request)

    assert order.symbol == "ETH/USDT"
    assert order.side == OrderSide.SELL
    assert order.order_type == "limit"
    assert order.quantity == 1.0
    assert order.price == 3000.0
    assert order.strategy_id == "strat-x"
    assert order.params == {"reduceOnly": True}
    # params is a copy — mutating order.params does not touch the request.
    order.params["clientOrderId"] = "c1"
    assert "clientOrderId" not in request.params


# ---------------------------------------------------------------------------
# build_close_request — opposing close OrderRequest (reduceOnly)
# ---------------------------------------------------------------------------


def test_build_close_request_for_long_position_uses_sell_reduceonly() -> None:
    """ISS-20260723-003: a long position closes with a SELL market order,
    reduceOnly=True (SEC-H2 — no flip into a new short)."""
    router = OrderRouter()
    pos = Position(
        symbol="BTC/USDT",
        quantity=0.5,
        entry_price=50000.0,
        current_price=51000.0,
    )

    request = router.build_close_request(pos)

    assert request.symbol == "BTC/USDT"
    assert request.side == OrderSide.SELL
    assert request.order_type == "market"
    assert request.quantity == 0.5
    assert request.strategy_id == "close_position"
    assert request.params == {"reduceOnly": True}


def test_build_close_request_for_short_position_uses_buy() -> None:
    """ISS-20260723-003: a short position (negative qty) closes with BUY."""
    router = OrderRouter()
    pos = Position(
        symbol="BTC/USDT",
        quantity=-0.3,
        entry_price=50000.0,
        current_price=49000.0,
    )

    request = router.build_close_request(pos)

    assert request.side == OrderSide.BUY
    assert request.quantity == 0.3
    assert request.params == {"reduceOnly": True}


# ---------------------------------------------------------------------------
# is_closeable — POSITION_EPSILON guard
# ---------------------------------------------------------------------------


def test_is_closeable_rejects_none_and_trivial_size() -> None:
    """ISS-20260723-003: is_closeable owns the single definition of 'closeable'
    — None or sub-epsilon positions are not closeable."""
    assert OrderRouter.is_closeable(None) is False
    assert (
        OrderRouter.is_closeable(
            Position(symbol="X", quantity=1e-12, entry_price=1.0, current_price=1.0)
        )
        is False
    )


def test_is_closeable_accepts_nontrivial_size() -> None:
    """ISS-20260723-003: a position above POSITION_EPSILON is closeable."""
    pos = Position(symbol="BTC/USDT", quantity=0.5, entry_price=50000.0, current_price=51000.0)
    assert OrderRouter.is_closeable(pos) is True
