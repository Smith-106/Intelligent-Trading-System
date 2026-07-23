"""OKX exchange gateway via CCXT async."""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

from quantflow.common.models import Order, OrderSide, Position
from quantflow.common.validators import validate_quantity, validate_symbol
from quantflow.execution.gateway_base import GatewayBase, GatewayError

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

    def __init__(self, sandbox: bool = True) -> None:
        self._sandbox = sandbox
        self._exchange: Any = None
        self._connected = False
        self._reconnect_interval = RECONNECT_INTERVAL
        self._max_reconnect_attempts = MAX_RECONNECT_ATTEMPTS

    async def connect(self, config: dict[str, Any] | None = None) -> None:
        import ccxt.async_support as ccxt

        cfg = config or {}
        self._exchange = ccxt.okx(
            {
                "apiKey": cfg.get("api_key", ""),
                "secret": cfg.get("secret", ""),
                "password": cfg.get("passphrase", ""),
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            }
        )

        if self._sandbox or cfg.get("sandbox", False):
            self._exchange.set_sandbox_mode(True)
            logger.info("OKX Gateway: SANDBOX mode")

        await self._exchange.load_markets()
        self._connected = True
        logger.info("OKX Gateway connected: %d markets", len(self._exchange.markets))

    async def disconnect(self) -> None:
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
                return
            except Exception as e:
                last_err = e
                logger.error("Reconnect attempt %d failed: %s", attempt, _safe_error(e))
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
        """
        if not self._exchange:
            raise GatewayError("query_positions: gateway not connected")
        try:
            raw = await asyncio.wait_for(self._exchange.fetch_positions(), timeout=CALL_TIMEOUT)
        except TimeoutError as e:
            self._connected = False
            logger.error("OKX query positions timed out")
            raise GatewayError("fetch_positions timed out") from e
        except Exception as e:
            self._connected = False
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

    @property
    def is_connected(self) -> bool:
        return self._connected
