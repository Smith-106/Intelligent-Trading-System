"""Execution engine — orchestrates order routing, timeout management, and fills."""

from __future__ import annotations

import logging
from time import perf_counter
from typing import TYPE_CHECKING, Any

from quantflow.common.event_bus import Event, EventBus
from quantflow.common.models import (
    Order,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
)
from quantflow.common.monitoring_sink import MonitoringSink, NullMonitoringSink
from quantflow.common.redaction import redact_secrets
from quantflow.common.validators import POSITION_EPSILON
from quantflow.execution.gateway_base import GatewayBase, GatewayError
from quantflow.execution.kill_switch import KillSwitch
from quantflow.execution.okx_gateway import OKXGateway
from quantflow.execution.order_manager import OrderManager
from quantflow.execution.paper_gateway import PaperGateway
from quantflow.execution.position_manager import PositionManager

if TYPE_CHECKING:
    from quantflow.signal.portfolio import PortfolioManager

EVENT_ORDER = "order"
EVENT_FILL = "fill"

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
        kill_switch: KillSwitch | None = None,
        monitoring_sink: MonitoringSink | None = None,
        portfolio: PortfolioManager | None = None,
    ) -> None:
        self._gateway = gateway
        self._event_bus = event_bus
        self._timeout = timeout
        self._order_mgr = OrderManager(timeout=int(timeout))
        # L5 PositionManager is a thin delegate over L4 (ISS-20260720-004 Wave 2).
        # When TradingSession constructs the engine before PortfolioManager
        # exists, pass None here and call set_portfolio() after; the
        # PositionManager creates a private default L4 so submit() works in
        # standalone/test usage too.
        self._position_mgr = PositionManager(portfolio=portfolio)
        self._portfolio: PortfolioManager | None = portfolio
        # L5→L6 seam (ISS-20260724-044): ExecutionEngine depends on the
        # MonitoringSink Protocol only; the concrete sink is injected by
        # TradingSession (shared with KillSwitch/RiskEngine). Default Null =
        # no-op. Removed the top-level ORDER_LATENCY/ORDERS_FILLED/ORDERS_TOTAL
        # import that coupled L5 to L6.
        self._sink: MonitoringSink = monitoring_sink or NullMonitoringSink()
        # Kill switch enforcement (odyssey-improve SEC-H4): when present, submit
        # refuses new orders while the kill switch is active. TradingSession
        # injects the same KillSwitch instance it owns so the engine-level gate
        # and the on_bar gate share one source of truth.
        self._kill_switch = kill_switch

    def set_kill_switch(self, kill_switch: KillSwitch | None) -> None:
        """Inject (or clear) the kill switch after construction.

        TradingSession builds the KillSwitch after the engine exists (it needs
        the gateway), then wires it here so submit() can enforce it.
        (odyssey-improve SEC-H4)
        """
        self._kill_switch = kill_switch

    def set_portfolio(self, portfolio: PortfolioManager) -> None:
        """Inject the shared L4 portfolio after construction (ISS-20260720-004 Wave 2).

        TradingSession constructs ExecutionEngine before PortfolioManager; this
        rebinds PositionManager to the shared L4 so submit()'s fill updates land
        on the same book _process_signal reads. Idempotent.
        """
        self._portfolio = portfolio
        self._position_mgr.bind_portfolio(portfolio)

    async def start(
        self, mode: str = "paper", gateway_config: dict[str, Any] | None = None
    ) -> None:
        """Initialize gateway based on mode."""
        if self._gateway is not None:
            await self._gateway.connect(gateway_config)
            return

        if mode == "paper":
            self._gateway = PaperGateway(gateway_config)
        elif mode in ("live", "okx"):
            self._gateway = OKXGateway(
                sandbox=gateway_config.get("sandbox", True) if gateway_config else True
            )
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

        started_at = perf_counter()

        # Kill switch enforcement (odyssey-improve SEC-H4): block new submissions
        # the moment the switch is active, regardless of which caller path
        # reaches submit (on_bar, web, close_position). This closes the race
        # where an in-flight signal submits after activate() begins.
        if self._kill_switch is not None and self._kill_switch.is_active:
            order.status = OrderStatus.REJECTED
            logger.warning(
                "Order rejected — kill switch active (reason=%s): symbol=%s side=%s strategy=%s",
                self._kill_switch.reason,
                order.symbol,
                order.side.value,
                order.strategy_id,
            )
            self._record_order_latency(order.symbol, started_at)
            return order

        try:
            exchange_id = await self._gateway.send_order(order)
        except Exception as e:
            order.status = OrderStatus.REJECTED
            # odyssey-review RP2 (SEC, CWE-532): gateway re-raises raw CCXT
            # exceptions whose message may embed OKX apiKey/URL. Scrub before
            # logging so credentials never reach the server log.
            logger.error(
                "Order rejected by gateway: symbol=%s side=%s strategy=%s err=%s",
                order.symbol,
                order.side.value,
                order.strategy_id,
                redact_secrets(str(e)),
            )
            self._record_order_latency(order.symbol, started_at)
            # Count and publish the rejection too (odyssey-improve OBS-H1):
            # previously the REJECTED branch skipped ORDERS_TOTAL + EVENT_ORDER,
            # so rejections were invisible in dashboards and the event stream.
            self._sink.record_order_total(
                symbol=order.symbol,
                side=order.side.value,
                strategy_id=order.strategy_id,
            )
            if self._event_bus:
                self._event_bus.publish(
                    Event(
                        type=EVENT_ORDER,
                        data={
                            "order_id": order.order_id,
                            "symbol": order.symbol,
                            "side": order.side.value,
                            "status": OrderStatus.REJECTED.value,
                        },
                    )
                )
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
                status=order.status,
                symbol=order.symbol,
                side=order.side.value,
                filled_quantity=order.filled_quantity,
                average_price=order.filled_price,
                fee=order.fee,
            ),
        )

        self._sink.record_order_total(
            symbol=order.symbol,
            side=order.side.value,
            strategy_id=order.strategy_id,
        )

        if self._event_bus:
            self._event_bus.publish(
                Event(
                    type=EVENT_ORDER,
                    data={
                        "order_id": exchange_id,
                        "symbol": order.symbol,
                        "side": order.side.value,
                        "status": order.status.value,
                    },
                )
            )

        # For paper/market orders, gateway fills immediately
        if order.status == OrderStatus.FILLED:
            self._order_mgr.update(
                exchange_id,
                OrderStatus.FILLED,
                filled_quantity=order.filled_quantity,
                filled_price=order.filled_price,
            )
            qty_signed = (
                order.filled_quantity if order.side == OrderSide.BUY else -order.filled_quantity
            )
            # ISS-20260720-004 Wave 2: L4 fill update is owned by engine.submit
            # (single source). PositionManager delegates to L4, fee included so
            # cash is debited once. _process_signal no longer re-updates L4.
            self._position_mgr.update_position(
                order.symbol,
                qty_signed,
                order.filled_price,
                fee=order.fee,
                strategy_id=order.strategy_id,
            )

            self._sink.record_order_filled(
                symbol=order.symbol,
                side=order.side.value,
                strategy_id=order.strategy_id,
            )

            if self._event_bus:
                self._event_bus.publish(
                    Event(
                        type=EVENT_FILL,
                        data={
                            "order_id": exchange_id,
                            "symbol": order.symbol,
                            "side": order.side.value,
                            "quantity": order.filled_quantity,
                            "price": order.filled_price,
                        },
                    )
                )

        self._record_order_latency(order.symbol, started_at)
        return order

    def update_market_price(self, symbol: str, price: float) -> None:
        """Update local mark price and propagate it to gateways that need a reference price."""
        self._position_mgr.update_market_price(symbol, price)
        # Call the declared base method directly (odyssey-improve ARCH-M2):
        # previously getattr/callable duck-typed past the interface into
        # PaperGateway, so OKXGateway silently dropped mark updates. Now both
        # gateways honor the contract — OKX via the base no-op. Guard for the
        # not-yet-started case (no gateway) to match the old getattr fallback.
        if self._gateway is not None:
            self._gateway.update_market_price(symbol, price)

    def _record_order_latency(self, symbol: str, started_at: float) -> None:
        self._sink.record_order_latency(symbol, perf_counter() - started_at)

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
            params=dict(request.params),
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
        if pos is None or abs(pos.quantity) < POSITION_EPSILON:
            return None

        side = OrderSide.SELL if pos.quantity > 0 else OrderSide.BUY
        qty = abs(pos.quantity)
        request = OrderRequest(
            symbol=symbol,
            side=side,
            order_type="market",
            quantity=qty,
            strategy_id="close_position",
            # reduceOnly (odyssey-improve SEC-H2): a flatten order must not
            # flip into a new opposite-side position if the held quantity has
            # already decreased between sizing and submit.
            params={"reduceOnly": True},
        )
        return await self.submit_order(request)

    def check_timeouts(self) -> list[tuple[str, str]]:
        """Check and return timed-out (order_id, symbol) pairs.

        Pairs (not bare ids) so callers can cancel on the exchange — cancel
        needs the symbol. (odyssey-improve REL-H4)
        """
        return self._order_mgr.check_timeouts()

    async def sync_positions(self) -> None:
        """Sync positions from the exchange.

        Fail-closed (odyssey-improve SEC-H5): on GatewayError do NOT zero out
        the local book — a failed query previously overwrote real positions
        with an empty list. Keep last-known state and log for manual sync.
        """
        if not self._gateway:
            return
        try:
            positions = await self._gateway.query_positions()
        except GatewayError as e:
            logger.error(
                "sync_positions skipped — query failed, keeping last-known: %s",
                redact_secrets(str(e)),
            )
            return
        for pos in positions:
            # Delegate to L4 (ISS-20260720-004 Wave 2): exchange is the source
            # of truth on live sync, so overwrite the local book rather than
            # the prior private-attribute write that left L4 stale.
            self._position_mgr.set_position(pos.symbol, pos)
        logger.info("Synced %d positions from exchange", len(positions))
