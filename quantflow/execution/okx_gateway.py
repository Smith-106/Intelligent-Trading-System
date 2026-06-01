"""OKX exchange gateway via CCXT async."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from quantflow.common.models import Order, OrderSide, Position
from quantflow.execution.gateway_base import GatewayBase

logger = logging.getLogger(__name__)

RECONNECT_INTERVAL = 5
MAX_RECONNECT_ATTEMPTS = 5


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
        self._exchange = ccxt.okx({
            "apiKey": cfg.get("api_key", ""),
            "secret": cfg.get("secret", ""),
            "password": cfg.get("passphrase", ""),
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })

        if self._sandbox or cfg.get("sandbox", False):
            self._exchange.set_sandbox_mode(True)
            logger.info("OKX Gateway: SANDBOX mode")

        await self._exchange.load_markets()
        self._connected = True
        logger.info("OKX Gateway connected: %d markets", len(self._exchange.markets))

    async def disconnect(self) -> None:
        if self._exchange:
            await self._exchange.close()
            self._exchange = None
        self._connected = False

    async def ensure_connected(self) -> None:
        """Check connection and attempt reconnect if needed."""
        if self._connected and self._exchange:
            return

        logger.warning("OKX Gateway disconnected — attempting reconnect")
        for attempt in range(1, self._max_reconnect_attempts + 1):
            try:
                await self.connect()
                logger.info("Reconnected on attempt %d", attempt)
                return
            except Exception as e:
                logger.error("Reconnect attempt %d failed: %s", attempt, e)
                if attempt < self._max_reconnect_attempts:
                    await asyncio.sleep(self._reconnect_interval)

        logger.critical("Failed to reconnect after %d attempts", self._max_reconnect_attempts)

    async def send_order(self, order: Order) -> str:
        """Submit an order to OKX."""
        if not self._exchange:
            raise RuntimeError("Not connected")

        await self.ensure_connected()

        side = "buy" if order.side == OrderSide.BUY else "sell"
        try:
            result = await self._exchange.create_order(
                symbol=order.symbol,
                type=order.order_type,
                side=side,
                amount=order.quantity,
                price=order.price,
            )
            order_id = str(result.get("id", ""))
            logger.info("OKX order placed: %s %s %.6f", side, order.symbol, order.quantity)
            return order_id
        except Exception as e:
            logger.error("OKX order failed: %s", e)
            self._connected = False
            raise

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        if not self._exchange:
            return False
        try:
            await self._exchange.cancel_order(order_id, symbol)
            logger.info("OKX cancel: %s", order_id)
            return True
        except Exception as e:
            logger.error("OKX cancel failed: %s", e)
            return False

    async def cancel_all_orders(self, symbol: str | None = None) -> list[bool]:
        if not self._exchange:
            return []
        try:
            params = {"symbol": symbol} if symbol else {}
            result = await self._exchange.cancel_all_orders(params)
            ids = [o.get("id", "") for o in result] if isinstance(result, list) else []
            logger.info("OKX cancel all: %d orders", len(ids))
            return [True] * len(ids)
        except Exception as e:
            logger.error("OKX cancel all failed: %s", e)
            return []

    async def query_positions(self) -> list[Position]:
        if not self._exchange:
            return []
        try:
            raw = await self._exchange.fetch_positions()
            positions = []
            for p in raw:
                qty = float(p.get("contracts", 0))
                if qty > 0:
                    positions.append(Position(
                        symbol=p["symbol"],
                        quantity=qty,
                        entry_price=float(p.get("entryPrice", 0)),
                        current_price=float(p.get("markPrice", 0)),
                        unrealized_pnl=float(p.get("unrealizedPnl", 0)),
                    ))
            return positions
        except Exception as e:
            logger.error("OKX query positions failed: %s", e)
            self._connected = False
            return []

    @property
    def is_connected(self) -> bool:
        return self._connected
