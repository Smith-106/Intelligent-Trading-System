"""OKX exchange gateway via CCXT async."""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
from typing import Any

from quantflow.common.models import Order, OrderSide, OrderStatus, Position
from quantflow.common.monitoring_sink import MonitoringSink, NullMonitoringSink
from quantflow.common.validators import POSITION_EPSILON, validate_quantity, validate_symbol
from quantflow.execution.gateway_base import GatewayBase, GatewayError, OpenOrder

logger = logging.getLogger(__name__)

RECONNECT_INTERVAL = 5
MAX_RECONNECT_ATTEMPTS = 5

# Per-call CCXT timeout (odyssey-improve REL-C1). The OrderManager 30s watchdog
# is a separate, higher-level concern; this bounds each network call so a
# stalled exchange response cannot hang the trading loop indefinitely.
CALL_TIMEOUT = 10.0


def _safe_error(e: BaseException) -> str:
    """Render an exception for logging without leaking credentials.

    CCXT exceptions and their ``str()`` may include the request URL, headers,
    or API key/secret echoed back by the exchange on auth failures. Logging
    the raw exception (``%s``, e) therefore risks writing secrets to logs
    (ISS-20260613-004). Keep only the exception type name and a class-level
    description — never the message body — so operators see what failed
    without the credential surface.
    """
    cls = type(e).__name__
    # CCXT error classes carry a human label in .name (e.g. "AuthenticationError");
    # prefer it when present, otherwise fall back to the class name alone.
    label = getattr(e, "name", None) or cls
    return f"{label} (type={cls})"


class OKXGateway(GatewayBase):
    """OKX exchange gateway.

    Supports sandbox (testnet) and production modes.
    Implements the canonical GatewayBase interface.
    """

    def __init__(
        self,
        sandbox: bool = True,
        market_type: str = "spot",
        monitoring_sink: MonitoringSink | None = None,
    ) -> None:
        """Initialize the OKX gateway.

        ISS-20260723-005: ``market_type`` selects the OKX account/market scope
        and is honored both at ``connect`` (``options.defaultType``) and at
        ``query_positions`` (spot derives from ``fetch_balance``; swap reads
        the derivatives ``contracts`` schema). Default ``spot`` preserves the
        prior behavior. Valid values: ``spot`` | ``swap`` (OKX ``defaultType``
        vocabulary).

        ISS-20260723-011 (OBS-M): ``monitoring_sink`` drives the gateway
        connectivity gauge + disconnect/reconnect counters (arch-013: L5
        depends on the common/ Protocol, never imports monitoring/). Default
        Null = no observability.
        """
        if market_type not in ("spot", "swap"):
            raise ValueError(f"Invalid market_type {market_type!r}: expected 'spot' or 'swap'")
        self._sandbox = sandbox
        self._market_type = market_type
        self._exchange_obj_label = "okx"
        self._sink: MonitoringSink = monitoring_sink or NullMonitoringSink()
        self._exchange: Any = None
        self._connected = False
        self._reconnect_interval = RECONNECT_INTERVAL
        self._max_reconnect_attempts = MAX_RECONNECT_ATTEMPTS
        # ISS-003: WebSocket subscription state. _ws_tasks holds active watch
        # loops (ohlcv/orders); _running is the cancellation flag checked by
        # each loop so disconnect() can drain them cleanly.
        self._ws_tasks: list[asyncio.Task[Any]] = []
        self._running: bool = True

    async def connect(self, config: dict[str, Any] | None = None) -> None:
        import ccxt.async_support as ccxt

        cfg = config or {}
        # ISS-20260723-005: defaultType is now driven by market_type so connect()
        # and query_positions() agree on the account scope (the prior hardcode
        # of "spot" while query_positions read the derivatives "contracts"
        # schema was the gap this fixes).
        self._exchange = ccxt.okx(
            {
                "apiKey": cfg.get("api_key", ""),
                "secret": cfg.get("secret", ""),
                "password": cfg.get("passphrase", ""),
                "enableRateLimit": True,
                "options": {"defaultType": self._market_type},
            }
        )

        if self._sandbox or cfg.get("sandbox", False):
            self._exchange.set_sandbox_mode(True)
            logger.info("OKX Gateway: SANDBOX mode")

        await self._exchange.load_markets()
        self._connected = True
        # ISS-20260723-011 (OBS-M): surface connectivity as a gauge so a
        # Grafana panel/alert tracks liveness without log mining.
        self._sink.record_gateway_connected(self._exchange_obj_label, True)
        logger.info("OKX Gateway connected: %d markets", len(self._exchange.markets))

    async def disconnect(self) -> None:
        # ISS-003: stop all WebSocket watch loops before closing the exchange
        # so no orphaned task can call watch_* on a closed aiohttp session.
        self._running = False
        for task in self._ws_tasks:
            if not task.done():
                task.cancel()
        if self._ws_tasks:
            await asyncio.gather(*self._ws_tasks, return_exceptions=True)
        self._ws_tasks.clear()
        # try/finally: close() can raise on a half-torn aiohttp session; we must
        # still clear state so a later is_connected check cannot lie. (REL-M1)
        try:
            if self._exchange:
                await self._exchange.close()
        except Exception as e:
            logger.warning("OKX disconnect close failed: %s", _safe_error(e))
        finally:
            self._exchange = None
            self._connected = False
            # ISS-20260723-011 (OBS-M): record the disconnect (reason=shutdown
            # for explicit disconnect) + flip the liveness gauge to 0.
            self._sink.record_gateway_disconnect(self._exchange_obj_label, "shutdown")
            self._sink.record_gateway_connected(self._exchange_obj_label, False)

    async def ensure_connected(self) -> None:
        """Check connection and attempt reconnect if needed.

        Fail-closed (odyssey-improve SEC-H5/REL-H3): on total reconnect failure
        raise ``GatewayError`` so callers (send_order, KillSwitch) cannot
        proceed against a dead exchange and must degrade deliberately.
        """
        if self._connected and self._exchange:
            return

        logger.warning("OKX Gateway disconnected — attempting reconnect")
        last_err: BaseException | None = None
        for attempt in range(1, self._max_reconnect_attempts + 1):
            try:
                await self.connect()
                logger.info("Reconnected on attempt %d", attempt)
                # ISS-20260723-011 (OBS-M): successful reconnect.
                self._sink.record_gateway_reconnect(self._exchange_obj_label, True)
                return
            except Exception as e:
                last_err = e
                logger.error("Reconnect attempt %d failed: %s", attempt, _safe_error(e))
                # ISS-20260723-011 (OBS-M): failed reconnect attempt — repeated
                # failures alert on a flapping exchange.
                self._sink.record_gateway_reconnect(self._exchange_obj_label, False)
                if attempt < self._max_reconnect_attempts:
                    await asyncio.sleep(self._reconnect_interval)

        raise GatewayError(
            f"Failed to reconnect after {self._max_reconnect_attempts} attempts"
        ) from last_err

    async def send_order(self, order: Order) -> str:
        """Submit an order to OKX."""
        if not self._exchange:
            raise RuntimeError("Not connected")

        # Numeric safety (validate_quantity rejects NaN/inf/<=0, replacing the
        # opaque ``x == x`` NaN trick that did not catch +inf). A bad quantity
        # is rejected here before create_order can echo request details. (MAIN-M)
        validate_quantity(order.quantity)
        # ISS-020: validate symbol at the execution choke point. order.symbol
        # can originate from a web-influenced signal path; reject a malformed
        # symbol before it reaches create_order (whose error body may echo it).
        validate_symbol(order.symbol)
        await self.ensure_connected()

        side = "buy" if order.side == OrderSide.BUY else "sell"
        # Forward exchange-specific params (e.g. reduceOnly for FLAT/close orders)
        # so a SELL that flattens a long cannot accidentally open a new short on
        # the live exchange. NOTE: PaperGateway does NOT yet consume order.params
        # (reduceOnly is silently ignored in paper mode) — a paper/live parity
        # gap tracked as an issue; the comment here previously claimed symmetry
        # which was false (odyssey-review ARCH finding).
        params: dict[str, Any] = dict(order.params) if order.params else {}
        # Idempotency (odyssey-improve REL-C2/SEC-H3): inject a clientOrderId so
        # a retried submit after a network ambiguity is deduped by the exchange
        # rather than producing a second live order. order_id is the local id.
        if order.order_id and "clientOrderId" not in params:
            params["clientOrderId"] = order.order_id
        try:
            result = await asyncio.wait_for(
                self._exchange.create_order(
                    symbol=order.symbol,
                    type=order.order_type,
                    side=side,
                    amount=order.quantity,
                    price=order.price,
                    params=params,
                ),
                timeout=CALL_TIMEOUT,
            )
            order_id = str(result.get("id", ""))
            # ISS-20260720-004 Wave 4: cumulative-fill contract. ccxt's unified
            # ``filled``/``average``/``fee.cost`` are cumulative (filled is the
            # total filled so far, not a per-call delta). Stamp them on the order
            # so ExecutionEngine.submit applies the incremental delta to L4
            # (filled - applied_filled_qty) without double-counting. OKX REST
            # create_order returns the final state for market orders; limit
            # orders may return 0/partial. Live partial-fill *auto*-sensing via
            # ws (watch_orders) is NOT implemented — this only captures what the
            # create_order response carries.
            filled_qty = float(result.get("filled", 0.0) or 0.0)
            avg_price = float(result.get("average", 0.0) or 0.0)
            fee_cost = float((result.get("fee", {}) or {}).get("cost", 0.0) or 0.0)
            if filled_qty > 0:
                order.filled_quantity = filled_qty
                order.filled_price = avg_price
                order.fee = fee_cost
                if filled_qty >= order.quantity - POSITION_EPSILON:
                    order.status = OrderStatus.FILLED
                else:
                    order.status = OrderStatus.PARTIAL
            logger.info(
                "OKX order placed: oid=%s side=%s %s %.6f",
                order_id,
                side,
                order.symbol,
                order.quantity,
            )
            return order_id
        except TimeoutError as e:
            logger.error(
                "OKX order timed out: symbol=%s side=%s qty=%.6f",
                order.symbol,
                side,
                order.quantity,
            )
            self._connected = False
            # ISS-20260723-011 (OBS-M): record the disconnect (reason=timeout)
            # + flip liveness gauge so the panel reflects the drop.
            self._sink.record_gateway_disconnect(self._exchange_obj_label, "timeout")
            self._sink.record_gateway_connected(self._exchange_obj_label, False)
            raise GatewayError("create_order timed out") from e
        except Exception as e:
            logger.error(
                "OKX order failed: %s symbol=%s side=%s qty=%.6f",
                _safe_error(e),
                order.symbol,
                side,
                order.quantity,
            )
            self._connected = False
            # ISS-20260723-011 (OBS-M): record the disconnect (reason=error).
            self._sink.record_gateway_disconnect(self._exchange_obj_label, "error")
            self._sink.record_gateway_connected(self._exchange_obj_label, False)
            raise

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        if not self._exchange:
            return False
        # ISS-020: validate symbol at the execution choke point.
        validate_symbol(symbol)
        try:
            await asyncio.wait_for(
                self._exchange.cancel_order(order_id, symbol), timeout=CALL_TIMEOUT
            )
            logger.info("OKX cancel: %s", order_id)
            return True
        except TimeoutError as e:
            logger.error("OKX cancel timed out: oid=%s symbol=%s", order_id, symbol)
            raise GatewayError("cancel_order timed out") from e
        except Exception as e:
            logger.error("OKX cancel failed: %s oid=%s", _safe_error(e), order_id)
            return False

    async def cancel_all_orders(self, symbol: str | None = None) -> list[bool]:
        if not self._exchange:
            return []
        if symbol is not None:
            # ISS-020: validate symbol at the execution choke point.
            validate_symbol(symbol)
        try:
            params = {"symbol": symbol} if symbol else {}
            result = await asyncio.wait_for(
                self._exchange.cancel_all_orders(params), timeout=CALL_TIMEOUT
            )
            ids = [o.get("id", "") for o in result] if isinstance(result, list) else []
            logger.info("OKX cancel all: %d orders", len(ids))
            return [True] * len(ids)
        except TimeoutError as e:
            logger.error("OKX cancel all timed out")
            raise GatewayError("cancel_all_orders timed out") from e
        except Exception as e:
            logger.error("OKX cancel all failed: %s", _safe_error(e))
            return []

    async def query_positions(self) -> list[Position]:
        """Query open positions from the exchange.

        Fail-closed (odyssey-improve SEC-H5/REL-H2): on failure raise
        ``GatewayError`` instead of returning ``[]`` — an empty list is
        indistinguishable from "no positions" and caused KillSwitch to report
        a successful activation while real positions stayed open. Genuine
        empty results still return ``[]``.

        ISS-20260723-005: branch on ``market_type``. In ``swap`` mode OKX
        ``fetch_positions`` returns the derivatives schema (contracts /
        entryPrice / markPrice / unrealizedPnl). In ``spot`` mode spot
        accounts have no persistent derivatives positions — ``fetch_positions``
        returns ``[]`` — so the contract would be silently unsatisfiable.
        Spot mode derives holdings from ``fetch_balance``: each non-quote
        asset with a non-zero free+used total is a Position. Spot has no
        leverage/entry notion, so ``entry_price`` and ``unrealized_pnl`` are
        set from the last trade price when available and 0 otherwise (the
        mark price comes from the balance snapshot's no value, not a live
        mark — documented limitation of spot mode).
        """
        if not self._exchange:
            raise GatewayError("query_positions: gateway not connected")
        if self._market_type == "swap":
            return await self._query_swap_positions()
        return await self._query_spot_positions()

    async def query_open_orders(self, symbol: str) -> list[OpenOrder]:
        """Query currently open orders from OKX exchange.

        ISS-20260720-004 (Reconciliation): Enables detection of orphan orders
        that exist on the exchange but are not tracked locally. Uses CCXT's
        fetch_open_orders() with timeout and fail-closed semantics.

        Args:
            symbol: Trading pair (e.g., "BTC/USDT")

        Returns:
            List of OpenOrder objects for all open orders.

        Raises:
            GatewayError: If query fails (network error, timeout, etc.)
        """
        if not self._exchange:
            raise GatewayError("query_open_orders: gateway not connected")
        validate_symbol(symbol)
        try:
            raw = await asyncio.wait_for(
                self._exchange.fetch_open_orders(symbol=symbol),
                timeout=CALL_TIMEOUT,
            )
        except TimeoutError as e:
            self._record_disconnect("timeout")
            logger.error("OKX query_open_orders timed out for %s", symbol)
            raise GatewayError("fetch_open_orders timed out") from e
        except Exception as e:
            self._record_disconnect("error")
            logger.error("OKX query_open_orders failed: %s", _safe_error(e))
            raise GatewayError("fetch_open_orders failed") from e

        orders: list[OpenOrder] = []
        for o in raw:
            try:
                orders.append(OpenOrder(
                    id=str(o.get("id", "")),
                    symbol=o.get("symbol", symbol),
                    side=str(o.get("side", "")),
                    order_type=str(o.get("type", "")),
                    price=float(o.get("price", 0) or 0),
                    filled_amount=float(o.get("filled", 0) or 0),
                    status=str(o.get("status", "open")),
                    timestamp=float(o.get("timestamp", 0) or 0),
                ))
            except (TypeError, ValueError) as e:
                logger.warning("OKX skipping malformed open order row: %s", _safe_error(e))
                continue
        return orders

    def _record_disconnect(self, reason: str) -> None:
        """Mark the gateway disconnected + emit OBS-M metrics (ISS-20260723-011).

        Centralizes the connect-state drop + disconnect counter + liveness
        gauge flip so every connection-loss branch (send_order/query_positions
        timeout/error) records consistently. ``reason`` is a short label
        (``timeout`` / ``error`` / ``shutdown``).
        """
        self._connected = False
        self._sink.record_gateway_disconnect(self._exchange_obj_label, reason)
        self._sink.record_gateway_connected(self._exchange_obj_label, False)

    async def _query_swap_positions(self) -> list[Position]:
        """Derivatives positions via ``fetch_positions`` (contracts schema)."""
        try:
            raw = await asyncio.wait_for(self._exchange.fetch_positions(), timeout=CALL_TIMEOUT)
        except TimeoutError as e:
            self._record_disconnect("timeout")
            logger.error("OKX query positions timed out")
            raise GatewayError("fetch_positions timed out") from e
        except Exception as e:
            self._record_disconnect("error")
            logger.error("OKX query positions failed: %s", _safe_error(e))
            raise GatewayError("fetch_positions failed") from e

        positions: list[Position] = []
        for p in raw:
            try:
                qty = float(p.get("contracts", 0) or 0)
                entry = float(p.get("entryPrice", 0) or 0)
                mark = float(p.get("markPrice", 0) or 0)
                upnl = float(p.get("unrealizedPnl", 0) or 0)
            except (TypeError, ValueError) as e:
                # Schema drift on one row must not collapse the whole query to
                # "no positions" — surface it and skip the bad row. (REL-H7)
                logger.warning("OKX skipping malformed position row: %s", _safe_error(e))
                continue
            # Validate the parsed values: reject NaN/inf (which float() does not).
            if not all(math.isfinite(v) for v in (qty, entry, mark, upnl)):
                logger.warning("OKX skipping non-finite position row: %s", p.get("symbol"))
                continue
            # abs() preserves short positions (qty<0) instead of dropping them.
            # The sign carries direction; Position.quantity is magnitude and
            # direction is encoded in OrderSide at the close path. (REL-H7)
            if abs(qty) > 0:
                positions.append(
                    Position(
                        symbol=p["symbol"],
                        quantity=abs(qty),
                        entry_price=entry,
                        current_price=mark,
                        unrealized_pnl=upnl,
                    )
                )
        return positions

    async def _query_spot_positions(self) -> list[Position]:
        """Spot holdings via ``fetch_balance`` (no derivatives schema).

        Spot mode has no persistent leveraged positions; OKX ``fetch_positions``
        returns ``[]``. To satisfy the ``query_positions`` contract for spot
        accounts, derive holdings from the spot balance: each asset with a
        non-zero free+used total becomes a Position. The quote currency
        (e.g. USDT) is excluded — it is cash, not a holding.

        ``entry_price``/``unrealized_pnl`` are best-effort: spot balances carry
        no entry-price or unrealized-PnL field, so both default to 0. The
        ``current_price`` is set from ``fetch_ticker`` when the market is
        available; otherwise 0. This is the documented spot limitation —
        KillSwitch flattens spot holdings by quantity, not by PnL.
        """
        try:
            balance = await asyncio.wait_for(self._exchange.fetch_balance(), timeout=CALL_TIMEOUT)
        except TimeoutError as e:
            self._record_disconnect("timeout")
            logger.error("OKX query spot balance timed out")
            raise GatewayError("fetch_balance timed out") from e
        except Exception as e:
            self._record_disconnect("error")
            logger.error("OKX query spot balance failed: %s", _safe_error(e))
            raise GatewayError("fetch_balance failed") from e

        positions: list[Position] = []
        # ccxt unified balance: {"info":..., "free": {asset: qty}, "used": {...},
        # "total": {...}}. Iterate total (free+used) and skip zero/quote.
        totals: dict[str, float] = {}
        for key in ("total", "free", "used"):
            bucket = balance.get(key) or {}
            if not isinstance(bucket, dict):
                continue
            for asset, raw_qty in bucket.items():
                try:
                    qty = float(raw_qty or 0)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(qty):
                    continue
                totals[asset] = max(totals.get(asset, 0.0), qty)
        for asset, qty in totals.items():
            if qty <= POSITION_EPSILON:
                continue
            # Skip quote currencies — they are cash, not holdings. Common OKX
            # quotes; a non-quote base asset (BTC/ETH/...) is a real holding.
            if asset in ("USDT", "USDC", "USD", "DAI"):
                continue
            # Best-effort mark price from the spot ticker; failures fall back
            # to 0 (documented spot limitation — no entry/PnL in spot mode).
            current_price = 0.0
            symbol = f"{asset}/USDT"
            try:
                ticker = await asyncio.wait_for(
                    self._exchange.fetch_ticker(symbol), timeout=CALL_TIMEOUT
                )
                current_price = float(ticker.get("last", 0.0) or 0.0)
            except Exception:
                # Ticker unavailable (delisted pair, rate limit) — leave 0.
                logger.debug("OKX spot: no ticker for %s, current_price=0", symbol)
            if not math.isfinite(current_price):
                current_price = 0.0
            positions.append(
                Position(
                    symbol=symbol,
                    quantity=qty,
                    entry_price=0.0,
                    current_price=current_price,
                    unrealized_pnl=0.0,
                )
            )
        return positions

    async def subscribe(self, channel: str, callback: Any = None) -> None:
        """Subscribe to WebSocket data via ccxt.pro.

        Supported channels: ``'ohlcv'``, ``'orders'``.
        Requires ccxt.pro (``pip install ccxt[pro]``).
        Falls back to a no-op with a warning when ccxt.pro is not installed
        so the REST polling path is never disturbed.
        """
        if not hasattr(self._exchange, "watch_ohlcv"):
            logger.warning("ccxt.pro not available — subscribe('%s') is no-op", channel)
            return

        handlers: dict[str, Any] = {
            "ohlcv": self._watch_ohlcv_loop,
            "orders": self._watch_orders_loop,
        }
        handler = handlers.get(channel)
        if handler is None:
            logger.warning("Unsupported WebSocket channel: %s", channel)
            return

        self._ws_tasks.append(asyncio.create_task(handler(callback)))

    async def _watch_ohlcv_loop(
        self,
        callback: Any,
        symbol: str = "BTC/USDT",
        timeframe: str = "1m",
    ) -> None:
        """Continuously watch OHLCV candles via WebSocket with reconnection.

        Uses exponential back-off (1 s → 2 s → … → 16 s cap) on errors so a
        flapping exchange cannot spin a hot reconnect loop.
        """
        backoff = 1.0
        while self._running:
            try:
                ohlcv = await self._exchange.watch_ohlcv(symbol, timeframe)
                if ohlcv and callback:
                    if inspect.iscoroutinefunction(callback):
                        await callback(ohlcv)
                    else:
                        callback(ohlcv)
                backoff = 1.0  # Reset on success
                # Yield to the event loop even on fast returns so this tight
                # loop cannot starve other coroutines (e.g. disconnect()).
                await asyncio.sleep(0)
            except Exception as e:
                logger.warning(
                    "watch_ohlcv error: %s, reconnecting in %.0fs",
                    type(e).__name__,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 16.0)

    async def _watch_orders_loop(
        self,
        callback: Any,
        symbol: str = "BTC/USDT",
    ) -> None:
        """Continuously watch private order updates via WebSocket.

        Same exponential-back-off reconnection strategy as ``_watch_ohlcv_loop``
        so a network partition degrades gracefully instead of spamming errors.
        """
        backoff = 1.0
        while self._running:
            try:
                orders = await self._exchange.watch_orders(symbol)
                if orders and callback:
                    if inspect.iscoroutinefunction(callback):
                        await callback(orders)
                    else:
                        callback(orders)
                backoff = 1.0
                await asyncio.sleep(0)  # Yield to event loop
            except Exception as e:
                logger.warning(
                    "watch_orders error: %s, reconnecting in %.0fs",
                    type(e).__name__,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 16.0)

    @property
    def is_connected(self) -> bool:
        return self._connected
