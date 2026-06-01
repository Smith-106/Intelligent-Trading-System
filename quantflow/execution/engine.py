"""Execution engine — orchestrates order routing, timeout management, and fills."""

from __future__ import annotations

import logging

from quantflow.common.event_bus import Event, EventBus
from quantflow.common.models import (
    Order,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
)

EVENT_ORDER = "order"
EVENT_FILL = "fill"
from quantflow.execution.gateway_base import GatewayBase
from quantflow.execution.okx_gateway import OKXGateway
from quantflow.execution.order_manager import OrderManager
from quantflow.execution.paper_gateway import PaperGateway
from quantflow.execution.position_manager import PositionManager

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Route orders through the gateway, track state, and emit fill events.

    Integrates with EventBus for ORDER and FILL events.
    """

    def __init__(
        self,
        gateway: GatewayBase | None = None,
        event_bus: EventBus | None = None,
        timeout: float = 30.0,
    ):
        self._gateway = gateway
        self._event_bus = event_bus
        self._timeout = timeout
        self._order_mgr = OrderManager(timeout=timeout)
        self._position_mgr = PositionManager()

    async def start(self, mode: str = "paper", gateway_config: dict | None = None) -> None:
        """Initialize gateway based on mode."""
        if self._gateway is not None:
            await self._gateway.connect(gateway_config)
            return

        if mode == "paper":
            self._gateway = PaperGateway(gateway_config)
        elif mode in ("live", "okx"):
            self._gateway = OKXGateway(sandbox=gateway_config.get("sandbox", True) if gateway_config else True)
        else:
            self._gateway = PaperGateway(gateway_config)

        await self._gateway.connect(gateway_config)
        logger.info("Execution engine started: mode=%s", mode)

    async def stop(self) -> None:
        """Stop the execution engine and disconnect gateway."""
        if self._gateway:
            await self._gateway.disconnect()
        logger.info("Execution engine stopped")

    @property
    def gateway(self) -> GatewayBase | None:
        return self._gateway

    @property
    def order_manager(self) -> OrderManager:
        return self._order_mgr

    @property
    def position_manager(self) -> PositionManager:
        return self._position_mgr

    async def submit(self, order: Order) -> Order:
        """Submit an Order object through the gateway.

        Args:
            order: Order object with symbol, side, type, quantity, price.

        Returns:
            Order object with updated status and fill info.
        """
        if not self._gateway:
            raise RuntimeError("Gateway not initialized — call start() first")

        try:
            exchange_id = await self._gateway.send_order(order)
        except Exception as e:
            order.status = OrderStatus.REJECTED
            logger.error("Order rejected by gateway: %s", e)
            return order
        order.order_id = exchange_id

        # Gateway may set status directly (FILLED for paper, REJECTED for errors)
        if order.status not in (OrderStatus.FILLED, OrderStatus.REJECTED):
            order.status = OrderStatus.SUBMITTED

        self._order_mgr.track(
            OrderRequest(
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                quantity=order.quantity,
                price=order.price,
                strategy_id=order.strategy_id,
            ),
            OrderResult(
                order_id=exchange_id,
                status=OrderStatus.SUBMITTED,
                symbol=order.symbol,
                side=order.side.value,
            ),
        )

        # Prometheus: track order submission
        from quantflow.monitoring.metrics import ORDERS_TOTAL
        ORDERS_TOTAL.labels(
            symbol=order.symbol, side=order.side.value, strategy_id=order.strategy_id,
        ).inc()

        if self._event_bus:
            self._event_bus.publish(Event(
                type=EVENT_ORDER,
                data={"order_id": exchange_id, "symbol": order.symbol,
                      "side": order.side.value, "status": "submitted"},
            ))

        # For paper/market orders, gateway fills immediately
        if order.status == OrderStatus.FILLED:
            self._order_mgr.update(
                exchange_id, OrderStatus.FILLED,
                filled_quantity=order.filled_quantity,
                filled_price=order.filled_price,
            )
            qty_signed = order.filled_quantity if order.side == OrderSide.BUY else -order.filled_quantity
            self._position_mgr.update_position(order.symbol, qty_signed, order.filled_price)

            # Prometheus: track order fill
            from quantflow.monitoring.metrics import ORDERS_FILLED
            ORDERS_FILLED.labels(
                symbol=order.symbol, side=order.side.value, strategy_id=order.strategy_id,
            ).inc()

            if self._event_bus:
                self._event_bus.publish(Event(
                    type=EVENT_FILL,
                    data={"order_id": exchange_id, "symbol": order.symbol,
                          "side": order.side.value, "quantity": order.filled_quantity,
                          "price": order.filled_price},
                ))

        return order

    async def submit_order(self, request: OrderRequest) -> Order:
        """Submit an OrderRequest through the gateway.

        Convenience method that creates an Order from OrderRequest and submits it.

        Args:
            request: OrderRequest with symbol, side, type, quantity, price.

        Returns:
            Order object with updated status and fill info.
        """
        order = Order(
            order_id="",
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            strategy_id=request.strategy_id,
        )
        return await self.submit(order)

    async def cancel(self, order_id: str, symbol: str) -> bool:
        """Cancel an order via the gateway."""
        if not self._gateway:
            return False
        success = await self._gateway.cancel_order(order_id, symbol)
        if success:
            self._order_mgr.update(order_id, OrderStatus.CANCELLED)
        return success

    async def close_position(self, symbol: str) -> Order | None:
        """Close an existing position by placing an opposing order."""
        pos = self._position_mgr.get_position(symbol)
        if pos is None or abs(pos.quantity) < 1e-10:
            return None

        side = OrderSide.SELL if pos.quantity > 0 else OrderSide.BUY
        qty = abs(pos.quantity)
        request = OrderRequest(
            symbol=symbol, side=side, order_type="market",
            quantity=qty, strategy_id="close_position",
        )
        return await self.submit_order(request)

    def check_timeouts(self) -> list[str]:
        """Check and return timed-out order IDs."""
        return self._order_mgr.check_timeouts()

    async def sync_positions(self) -> None:
        """Sync positions from the exchange."""
        if not self._gateway:
            return
        positions = await self._gateway.query_positions()
        for pos in positions:
            self._position_mgr._positions[pos.symbol] = pos
        logger.info("Synced %d positions from exchange", len(positions))
