"""Order manager — track order lifecycle and detect timeouts."""

from __future__ import annotations

import logging
import time

from quantflow.common.models import Order, OrderRequest, OrderResult, OrderStatus

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30  # seconds


class OrderManager:
    """Track order lifecycle: creation → fill/cancel/timeout."""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout
        self._orders: dict[str, Order] = {}
        self._pending: dict[str, float] = {}  # order_id → submit_timestamp

    def track(self, request: OrderRequest, result: OrderResult | None = None) -> Order:
        """Register a new order from a request and optional result."""
        order_id = result.order_id if result else f"local-{int(time.time() * 1000)}"
        order = Order(
            order_id=order_id,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            status=OrderStatus.SUBMITTED,
            strategy_id=request.strategy_id,
        )

        if result:
            order.status = result.status
            order.filled_quantity = getattr(result, "filled_quantity", 0.0)
            order.filled_price = getattr(result, "average_price", 0.0)
            order.fee = getattr(result, "fee", 0.0)
            if result.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
                pass  # already terminal
            else:
                self._pending[order_id] = time.time()
        else:
            self._pending[order_id] = time.time()

        self._orders[order_id] = order
        logger.info("Order tracked: %s %s %s", order_id, order.symbol, order.status.value)
        return order

    def update(
        self,
        order_id: str,
        status: OrderStatus,
        filled_quantity: float = 0.0,
        filled_price: float = 0.0,
        fee: float = 0.0,
    ) -> None:
        """Update order status from exchange callback."""
        order = self._orders.get(order_id)
        if not order:
            logger.warning("Unknown order update: %s", order_id)
            return

        order.status = status
        if filled_quantity > 0:
            order.filled_quantity = filled_quantity
            order.filled_price = filled_price
            order.fee = fee

        if status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
            self._pending.pop(order_id, None)

        logger.info(
            "Order %s → %s (filled=%.6f@%.2f)",
            order_id,
            status.value,
            filled_quantity,
            filled_price,
        )

    def check_timeouts(self) -> list[str]:
        """Return order IDs that have exceeded the timeout."""
        now = time.time()
        timed_out = [oid for oid, ts in self._pending.items() if now - ts > self._timeout]
        for oid in timed_out:
            logger.warning("Order timeout: %s (%ds)", oid, self._timeout)
            self._pending.pop(oid, None)
        return timed_out

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def get_open_orders(self) -> list[Order]:
        return [
            o
            for o in self._orders.values()
            if o.status
            in (
                OrderStatus.CREATED,
                OrderStatus.SUBMITTED,
                OrderStatus.ACCEPTED,
                OrderStatus.PARTIAL,
            )
        ]

    def get_orders_by_strategy(self, strategy_id: str) -> list[Order]:
        return [o for o in self._orders.values() if o.strategy_id == strategy_id]

    @property
    def total_orders(self) -> int:
        return len(self._orders)

    @property
    def pending_count(self) -> int:
        return len(self._pending)
