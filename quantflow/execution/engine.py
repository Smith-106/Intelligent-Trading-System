"""Execution engine — orchestrates order routing, timeout management, and fills."""

from __future__ import annotations

import asyncio
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
from quantflow.execution.order_router import OrderRouter
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
        # ISS-20260723-003: OrderRouter owns gateway dispatch + Order/Request
        # construction (the two order-shaping concerns submit/submit_order/
        # close_position previously inlined). arch-017 lazy binding — the
        # gateway is built by start() after the engine exists, so the router
        # starts unbound and is rebound via set_gateway on start.
        self._router = OrderRouter(gateway)
        self._event_bus = event_bus
        self._timeout = timeout
        # ISS-20260723-011 (OBS-M): OrderManager shares the injected sink so
        # the orders-timed-out counter lands on the same MonitoringSink as the
        # engine's order_total/filled/latency metrics.
        self._order_mgr = OrderManager(
            timeout=int(timeout),
            monitoring_sink=monitoring_sink,
        )
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
                sandbox=gateway_config.get("sandbox", True) if gateway_config else True,
                # ISS-20260723-005: propagate market_type so connect() defaultType
                # and query_positions() branch agree on spot vs swap scope.
                market_type=gateway_config.get("market_type", "spot") if gateway_config else "spot",
                # ISS-20260723-011 (OBS-M): share the engine's sink so gateway
                # connectivity gauge + disconnect/reconnect counters land on the
                # same MonitoringSink as the engine's order metrics.
                monitoring_sink=self._sink,
            )
        else:
            self._gateway = PaperGateway(gateway_config)

        # ISS-20260723-003: bind the freshly built gateway to the router so
        # submit()'s route() calls can dispatch (arch-017 lazy binding).
        self._router.set_gateway(self._gateway)
        await self._gateway.connect(gateway_config)
        logger.info("Execution engine started: mode=%s", mode)

    async def stop(self) -> None:
        """Stop the execution engine and disconnect gateway.

        ISS-20260723-012: CancelledError raised during ``gateway.disconnect()``
        (e.g. event-loop shutdown racing the await) is swallowed so a
        half-torn-down gateway does not surface a misleading traceback —
        ``stop()`` is idempotent and must not raise on cleanup paths.
        """
        if self._gateway:
            try:
                await self._gateway.disconnect()
            except asyncio.CancelledError:
                # loop-shutdown race: gateway teardown interrupted — log + continue
                logger.warning("Execution engine stop() interrupted (CancelledError)")
                raise
            except Exception as e:
                logger.warning("Execution engine stop() partial failure: %s", e)
        logger.info("Execution engine stopped")

    async def __aenter__(self) -> ExecutionEngine:
        """ISS-20260723-012: async context manager support — ``start()`` on
        enter. Callers that previously hand-managed ``start``/``stop`` in a
        ``try/finally`` can now use ``async with engine:`` for guaranteed
        teardown even on exception paths."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None:
        """ISS-20260723-012: guaranteed teardown on exit — delegates to
        ``stop()`` which is CancelledError-safe. Does not suppress the
        in-flight exception (no return True)."""
        await self.stop()

    @property
    def gateway(self) -> GatewayBase | None:
        # ISS-20260723-003: engine still owns gateway lifecycle (start/stop/
        # cancel/sync); the router holds the same reference for send_order
        # dispatch. Public API (engine.gateway) unchanged.
        return self._gateway

    @property
    def router(self) -> OrderRouter:
        # ISS-20260723-003: expose the router for tests / callers that need
        # Order construction without going through submit (e.g. dry-run sizing).
        return self._router

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
            # ISS-20260723-003: gateway dispatch moved to OrderRouter.route;
            # submit keeps the orchestration (kill-switch gate → route → track
            # → metric → event → fill) but no longer calls gateway.send_order.
            exchange_id = await self._router.route(order)
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

        # Gateway may set status directly (FILLED/PARTIAL for paper+OKX market,
        # REJECTED for errors). ISS-20260720-004 Wave 4: PARTIAL is now a
        # terminal-enough state to drive an L4 incremental update, so preserve
        # it (previously only FILLED/REJECTED survived this branch and PARTIAL
        # was silently downgraded to SUBMITTED, dropping the partial fill).
        if order.status not in (OrderStatus.FILLED, OrderStatus.PARTIAL, OrderStatus.REJECTED):
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

        # For paper/market orders, gateway fills immediately; OKX REST returns
        # final state for market orders. PARTIAL is reachable when a future ws
        # fill-callback (or an OKX limit that partially fills) reports a
        # cumulative filled_quantity below the requested qty.
        if order.status in (OrderStatus.FILLED, OrderStatus.PARTIAL):
            await self._handle_fill(order, exchange_id)

        self._record_order_latency(order.symbol, started_at)
        return order

    async def _handle_fill(self, order: Order, exchange_id: str) -> None:
        """Apply a FILLED/PARTIAL result to OrderManager + L4 + emit events.

        ISS-20260723-007: extracted from ``submit`` so the fill-handling
        concern (cumulative-fill delta → L4 incremental update, FILLED-only
        event/metric emission) is a named, testable unit instead of a deeply
        nested block inside the submit flow.

        ISS-20260720-004 Wave 4: ccxt/OKX report ``filled`` as a cumulative
        total; apply only the incremental delta (cumulative - already-applied)
        to L4 so repeated partial fills do not double-count. POSITION_EPSILON
        guards a zero delta (e.g. a repeated callback with no new fill).
        PARTIAL stays non-terminal (OrderManager keeps it pending) so
        downstream does not mistake a partial for a complete fill.
        """
        self._order_mgr.update(
            exchange_id,
            order.status,
            filled_quantity=order.filled_quantity,
            filled_price=order.filled_price,
            fee=order.fee,
        )
        delta_filled = order.filled_quantity - order.applied_filled_qty
        if delta_filled > POSITION_EPSILON:
            qty_signed = delta_filled if order.side == OrderSide.BUY else -delta_filled
            # Wave 2: PositionManager delegates to L4; fee is the cumulative
            # fee reported with this fill. Cash is debited once per delta.
            self._position_mgr.update_position(
                order.symbol,
                qty_signed,
                order.filled_price,
                fee=order.fee,
                strategy_id=order.strategy_id,
            )
            order.applied_filled_qty = order.filled_quantity

        # FILLED emits the fill event + records the metric; PARTIAL stays
        # non-terminal (OrderManager keeps it pending).
        if order.status == OrderStatus.FILLED:
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
        # ISS-20260723-003: Order construction moved to OrderRouter.build_order
        # (the shaping concern submit previously inlined).
        order = self._router.build_order(request)
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
        """Close an existing position by placing an opposing order.

        ISS-20260723-003: the close-request construction (opposing side +
        reduceOnly) moved to OrderRouter.build_close_request; submit keeps the
        orchestration. The POSITION_EPSILON closeable check is
        OrderRouter.is_closeable so the definition is owned once.
        """
        pos = self._position_mgr.get_position(symbol)
        if not self._router.is_closeable(pos):
            return None
        # is_closeable guarantees pos is not None; narrow for mypy + build_close_request.
        assert pos is not None
        request = self._router.build_close_request(pos)
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
