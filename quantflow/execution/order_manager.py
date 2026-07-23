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

        # Terminal-state guard (odyssey-improve REL-H5): once an order reaches a
        # terminal state (including the new TIMED_OUT/CANCELLED set by
        # check_timeouts) reject late callbacks so a fill cannot resurrect a
        # dead order into a second inconsistent truth.
        if order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
            logger.warning(
                "Ignoring update for terminal order %s (was %s, got %s)",
                order_id,
                order.status.value,
                status.value,
            )
            return

        # Partial fill (odyssey-improve REL-H6): distinguish partial from full
        # so position_manager is updated with the partial signed qty and the
        # order stays non-terminal until the rest fills or is cancelled.
        if filled_quantity > 0 and filled_quantity < order.quantity:
            order.status = OrderStatus.PARTIAL
            order.filled_quantity = filled_quantity
            order.filled_price = filled_price
            order.fee = fee
            logger.info(
                "Order %s → %s (filled=%.6f@%.2f of %.6f)",
                order_id,
                OrderStatus.PARTIAL.value,
                filled_quantity,
                filled_price,
                order.quantity,
            )
            # Partial stays pending — more may fill. Do not pop _pending.
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

    def check_timeouts(self) -> list[tuple[str, str]]:
        """Return (order_id, symbol) pairs that have exceeded the timeout.

        Marks each timed-out order CANCELLED in ``_orders`` (not just a
        ``_pending`` pop) so a late fill callback is rejected by the
        terminal-state guard instead of resurrecting a dead order
        (odyssey-improve REL-H4/H5). Returns (id, symbol) pairs so callers
        can cancel on the exchange — cancel needs the symbol.
        """
        now = time.time()
        timed_out: list[tuple[str, str]] = []
        for oid, ts in list(self._pending.items()):
            if now - ts <= self._timeout:
                continue
            order = self._orders.get(oid)
            symbol = order.symbol if order else ""
            logger.warning("Order timeout: %s (%ds)", oid, self._timeout)
            if order is not None:
                order.status = OrderStatus.CANCELLED
            self._pending.pop(oid, None)
            timed_out.append((oid, symbol))
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
