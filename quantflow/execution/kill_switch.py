"""Kill Switch — emergency stop for all trading activity."""

from __future__ import annotations

import logging
from typing import Any

from quantflow.common.models import Order, OrderSide
from quantflow.execution.gateway_base import GatewayBase

logger = logging.getLogger(__name__)


class KillSwitch:
    """Emergency kill switch to halt all trading and close positions.

    When activated:
    1. Cancel all pending orders
    2. Close all open positions with market orders
    3. Block any new order submissions
    """

    def __init__(self, gateway: GatewayBase) -> None:
        self._gateway = gateway
        self._active = False
        self._reason: str | None = None

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def reason(self) -> str | None:
        return self._reason

    async def activate(self, reason: str) -> dict[str, Any]:
        """Activate kill switch — cancel orders, close positions."""
        if self._active:
            logger.warning("Kill switch already active: %s", self._reason)
            return {"status": "already_active", "reason": self._reason}

        self._active = True
        self._reason = reason
        logger.critical("KILL SWITCH ACTIVATED: %s", reason)

        results: dict[str, Any] = {
            "status": "activated",
            "reason": reason,
            "cancelled_orders": [],
            "closed_positions": [],
            "errors": [],
        }

        try:
            # Step 1: Cancel all pending orders
            try:
                cancelled = await self._gateway.cancel_all_orders()
                results["cancelled_orders"] = cancelled
                logger.info("Cancelled %d orders", len(cancelled))
            except Exception as e:
                results["errors"].append(f"cancel_orders: {e}")
                logger.error("Failed to cancel orders: %s", e)

            # Step 2: Close all open positions with market orders
            try:
                positions = await self._gateway.query_positions()
                for pos in positions:
                    if abs(pos.quantity) > 0:
                        try:
                            side = OrderSide.SELL if pos.quantity > 0 else OrderSide.BUY
                            close_qty = abs(pos.quantity)
                            order = Order(
                                order_id="",
                                symbol=pos.symbol,
                                side=side,
                                order_type="market",
                                quantity=close_qty,
                            )
                            order_id = await self._gateway.send_order(order)
                            results["closed_positions"].append(
                                {
                                    "symbol": pos.symbol,
                                    "quantity": close_qty,
                                    "order_id": order_id,
                                }
                            )
                            logger.info("Closing %s %s: order %s", pos.symbol, close_qty, order_id)
                        except Exception as e:
                            results["errors"].append(f"close_{pos.symbol}: {e}")
                            logger.error("Failed to close %s: %s", pos.symbol, e)
            except Exception as e:
                results["errors"].append(f"query_positions: {e}")
                logger.error("Failed to query positions: %s", e)

        except Exception as e:
            results["errors"].append(f"unexpected: {e}")
            logger.critical("Unexpected error during kill switch: %s", e)

        return results

    def deactivate(self) -> None:
        """Deactivate kill switch — allow trading to resume."""
        self._active = False
        self._reason = None
        logger.info("Kill switch deactivated — trading may resume")

    def check(self) -> dict[str, Any]:
        """Return current kill switch status."""
        return {
            "active": self._active,
            "reason": self._reason,
        }
