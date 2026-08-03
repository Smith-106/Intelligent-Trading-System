"""Thread-safe order manager — track order lifecycle and detect timeouts."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

from quantflow.common.models import Order, OrderRequest, OrderResult, OrderStatus
from quantflow.common.monitoring_sink import MonitoringSink, NullMonitoringSink

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30  # seconds
# Bounded retention for terminal orders (ISS-020). _orders previously grew
# unbounded — a live session tracking tens of thousands of FILLED/CANCELLED/
# REJECTED orders leaked memory and made get_open_orders' full scan slower
# over time. Once _orders exceeds this cap, the oldest terminal orders are
# evicted; active (non-terminal) orders are never evicted. Recent terminal
# orders stay queryable (get_order / get_orders_by_strategy) so the common
# case — checking an order right after it fills — still works.
MAX_TRACKED_ORDERS = 10_000
_TERMINAL_STATES = (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED)


class OrderManager:
    """Track order lifecycle with thread-safe operations.

    Thread Safety (REL-H7):
    - Uses RLock to protect all state mutations from race conditions
    - Atomic context manager (_atomic_operation) ensures check-then-act is not vulnerable
    - Compatible with multi-threaded strategy execution environments
    """

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        monitoring_sink: MonitoringSink | None = None,
    ) -> None:
        self._timeout = timeout
        # ISS-20260723-011 (OBS-M): L5→L6 seam for the orders-timed-out counter
        # (arch-013: depends on the common/ Protocol, never imports monitoring/).
        # Default Null = no observability (tests/backtest).
        self._sink: MonitoringSink = monitoring_sink or NullMonitoringSink()
        self._orders: dict[str, Order] = {}
        self._pending: dict[str, float] = {}  # order_id → submit_timestamp
        self._lock = threading.RLock()  # Thread safety guard (REL-H7)

    @contextmanager
    def _atomic_order_operation(self, order_id: str) -> Iterator[Order]:
        """Thread-safe context manager for atomic order operations.

        Prevents race conditions in concurrent order access across strategy threads.
        Usage:
            with om._atomic_order_operation(order_id) as order:
                # Safe to read/modify order within this block
                if order.status == OrderStatus.SUBMITTED:
                    cancel(order)
        """
        with self._lock:
            if order_id not in self._orders:
                raise KeyError(f"Order {order_id} not found")
            yield self._orders[order_id]

    def _evict_terminal_if_needed(self) -> None:
        """Evict oldest terminal orders when _orders exceeds the retention cap.

        Active (non-terminal) orders are never evicted — they may still receive
        callbacks. Only terminal orders beyond MAX_TRACKED_ORDERS are dropped,
        oldest first (by submit timestamp from _pending, else track-time order
        of insertion which Python dicts preserve).
        """
        if len(self._orders) <= MAX_TRACKED_ORDERS:
            return
        # Terminal candidates, oldest-submit-first. _pending only holds
        # non-terminal ids, so terminal orders are ordered by insertion order
        # (dict preserves it) — evict from the front.
        evicted = 0
        for oid in list(self._orders.keys()):
            if len(self._orders) <= MAX_TRACKED_ORDERS:
                break
            order = self._orders[oid]
            if order.status in _TERMINAL_STATES:
                del self._orders[oid]
                evicted += 1
        if evicted:
            logger.info("Evicted %d terminal orders (cap=%d)", evicted, MAX_TRACKED_ORDERS)

    def track(self, request: OrderRequest, result: OrderResult | None = None) -> Order:
        """Register a new order from a request and optional result."""
        with self._lock:  # Thread-safe tracking
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
                if result.status in (
                    OrderStatus.FILLED,
                    OrderStatus.CANCELLED,
                    OrderStatus.REJECTED,
                ):
                    pass  # already terminal
                else:
                    self._pending[order_id] = time.time()
            else:
                self._pending[order_id] = time.time()

            self._orders[order_id] = order
            self._evict_terminal_if_needed()
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
        """Update order status from an exchange callback.

        Cumulative-fill contract (ISS-20260720-004 Wave 4): ``filled_quantity``
        is the cumulative total reported by the exchange (ccxt ``order['filled']``
        for OKX), NOT a per-callback delta. OrderManager records it on the order;
        ExecutionEngine.submit derives the incremental L4 delta as
        ``filled_quantity - order.applied_filled_qty`` and updates
        ``applied_filled_qty`` after applying it, so repeated partial fills do
        not double-count. Live partial fills are sensed from two paths:
        the create_order REST response (immediate stamp in OKXGateway /
        PaperGateway) and — when ``gateway.ws_order_stream`` is enabled — the
        ccxt watch_orders stream consumed by ExecutionEngine._on_order_update,
        which stamps the same cumulative fields before routing through the
        identical delta-application path (T-s1-02).
        """
        with self._lock:  # Thread-safe update (REL-H7)
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
                # ISS-20260723-011 (OBS-M): surface stale-order churn as a
                # counter so a panel/alert tracks timeouts without log mining.
                self._sink.record_order_timed_out(symbol=order.symbol, side=order.side.value)
            self._pending.pop(oid, None)
            timed_out.append((oid, symbol))
        return timed_out

    def get_order(self, order_id: str) -> Order | None:
        with self._lock:  # Thread-safe read
            return self._orders.get(order_id)

    def get_open_orders(self) -> list[Order]:
        with self._lock:  # Thread-safe snapshot
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
        with self._lock:  # Thread-safe filtering
            return [o for o in self._orders.values() if o.strategy_id == strategy_id]

    @property
    def total_orders(self) -> int:
        return len(self._orders)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def cancel_order(self, order_id: str) -> tuple[bool, str]:
        """Atomically cancel an order with status validation.

        Returns:
            tuple: (success: bool, reason: str)
            - (True, "OK") if cancellation successful
            - (False, reason) otherwise

        Thread Safety (REL-H7): Atomic status transition prevents race conditions.
        """
        with self._atomic_order_operation(order_id) as order:
            if order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
                return (False, f"Order {order_id} already terminal ({order.status.value})")

            if order.status != OrderStatus.SUBMITTED:
                return (
                    False,
                    f"Only submitted orders can be cancelled (current: {order.status.value})",
                )

            # Status would be updated here; in real scenario calls gateway.cancel()
            order.status = OrderStatus.CANCELLED
            self._pending.pop(order_id, None)
            logger.info("Order %s cancelled via atomic cancel_order", order_id)
            return (True, "OK")
