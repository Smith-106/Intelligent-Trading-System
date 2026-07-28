"""Order router — gateway dispatch + Order construction (ISS-20260723-003).

Extracted from ExecutionEngine to retire its god-object shape. ExecutionEngine
previously owned 7 responsibilities (routing / order state / event publish /
metric / Order construction / close_position / sync); ISS-003 moves the two
purely-order-construction concerns into OrderRouter so ExecutionEngine keeps
only the submit *orchestration* (kill-switch gate → route → track → metric →
event → fill handling) and degrades to a thin facade.

OrderRouter owns:
- ``route(order)`` — gateway ``send_order`` dispatch (the routing concern)
- ``build_order(request)`` — OrderRequest → Order construction
- ``build_close_request(position)`` — close-position OrderRequest (reduceOnly)

Lifecycle (arch-017 lazy binding, same pattern as set_portfolio): the gateway
is created by ExecutionEngine.start() AFTER the engine (and thus the router)
exists, so the router accepts ``gateway=None`` at construction and is rebound
via ``set_gateway`` once ExecutionEngine.start builds it. Before that, route()
raises the same "not initialized" error the prior inline gateway.send_order
call would have surfaced.
"""

from __future__ import annotations

import logging

from quantflow.common.models import Order, OrderRequest, OrderSide, Position
from quantflow.common.validators import POSITION_EPSILON
from quantflow.execution.gateway_base import GatewayBase

logger = logging.getLogger(__name__)


class OrderRouter:
    """Gateway dispatch + Order/Request construction (ISS-20260723-003).

    A thin helper that owns the three order-shaping concerns ExecutionEngine
    previously inlined. It holds no state beyond the gateway reference (lazily
    bound) and performs no metric/event bookkeeping — that stays in
    ExecutionEngine.submit's orchestration so the hot path's control flow is
    unchanged.
    """

    def __init__(self, gateway: GatewayBase | None = None) -> None:
        # arch-017 lazy binding: ExecutionEngine is constructed before its
        # gateway exists (start() builds it), so accept None and rebind via
        # set_gateway — mirroring ExecutionEngine.set_portfolio's pattern.
        self._gateway: GatewayBase | None = gateway

    def set_gateway(self, gateway: GatewayBase) -> None:
        """Rebind the gateway after ExecutionEngine.start builds it (arch-017).

        Idempotent — called once per start(). The router never owns gateway
        lifecycle (connect/disconnect stay in ExecutionEngine); it only
        references the gateway for send_order dispatch.
        """
        self._gateway = gateway

    @property
    def gateway(self) -> GatewayBase | None:
        return self._gateway

    async def route(self, order: Order) -> str:
        """Dispatch an Order to the gateway and return the exchange order id.

        Raises RuntimeError if no gateway is bound — the same "call start()
        first" contract ExecutionEngine.submit enforced inline before.
        """
        if self._gateway is None:
            raise RuntimeError("Gateway not initialized — call start() first")
        return await self._gateway.send_order(order)

    def build_order(self, request: OrderRequest) -> Order:
        """Construct an Order from an OrderRequest (the shaping concern).

        Pure transformation — no side effects. ``params`` is copied so the
        caller's request is not mutated by downstream order.params writes.
        """
        return Order(
            order_id="",
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            strategy_id=request.strategy_id,
            params=dict(request.params),
        )

    def build_close_request(self, position: Position) -> OrderRequest:
        """Construct the opposing close-position OrderRequest (SEC-H2 reduceOnly).

        Builds a market order for the held quantity on the opposite side with
        ``reduceOnly=True`` so a flatten cannot flip into a new opposite-side
        position if the held quantity decreased between sizing and submit.
        """
        side = OrderSide.SELL if position.quantity > 0 else OrderSide.BUY
        return OrderRequest(
            symbol=position.symbol,
            side=side,
            order_type="market",
            quantity=abs(position.quantity),
            strategy_id="close_position",
            params={"reduceOnly": True},
        )

    @staticmethod
    def is_closeable(position: Position | None) -> bool:
        """A position is closeable when it exists and has non-trivial size.

        Extracted so ExecutionEngine.close_position and any future caller share
        one definition of "closeable" (POSITION_EPSILON guard, same as before).
        """
        return position is not None and abs(position.quantity) >= POSITION_EPSILON
