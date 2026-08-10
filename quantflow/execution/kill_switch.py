"""Kill Switch — emergency stop for all trading activity."""

from __future__ import annotations

import logging
from typing import Any

from quantflow.common.models import Order, OrderSide
from quantflow.common.monitoring_sink import MonitoringSink, NullMonitoringSink
from quantflow.common.pause_reasons import PauseReasonSet
from quantflow.common.redaction import redact_secrets
from quantflow.execution.gateway_base import GatewayBase

logger = logging.getLogger(__name__)

# reduceOnly is CCXT's canonical camelCase param (SIG spec S-20260722-z4dr).
# Setting it on every flatten order prevents a SELL sized to a stale long
# quantity from opening a new short on the live exchange (odyssey-improve
# SEC-H2). PaperGateway and OKXGateway both honor order.params["reduceOnly"]
# (ISS-021 / ISS-20260803-005 closed): paper caps/rejects; live forwards to CCXT.
_REDUCE_ONLY_PARAMS = {"reduceOnly": True}


class KillSwitch:
    """Emergency kill switch to halt all trading and close positions.

    When activated:
    1. Cancel all pending orders
    2. Close all open positions with market orders (reduceOnly)
    3. Block any new order submissions

    Fail-closed posture (odyssey-improve SEC-H5/REL-H8): if query_positions
    raises ``GatewayError`` we do NOT report success with an empty close list
    — the emergency stop reports ``status="failed"`` so the operator knows
    real positions may still be open and must intervene manually.
    """

    def __init__(self, gateway: GatewayBase, monitoring_sink: MonitoringSink | None = None) -> None:
        self._gateway = gateway
        # L5→L6 seam (ISS-20260724-044): KillSwitch depends on the MonitoringSink
        # Protocol only; the concrete sink is injected by TradingSession
        # (shared with ExecutionEngine/RiskEngine). Default Null = no-op.
        # Removed the top-level KILL_SWITCH_ACTIVATIONS/STEP_FAILURES import.
        self._sink: MonitoringSink = monitoring_sink or NullMonitoringSink()
        self._active = False
        self._reason: str | None = None
        # OSS uplift: multi-reason pause set (kill_switch is one source).
        self.pause_reasons = PauseReasonSet()

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
            self.pause_reasons.add(reason or "kill_switch")
            return {"status": "already_active", "reason": self._reason}

        self._active = True
        self._reason = reason
        self.pause_reasons.add("kill_switch")
        if reason:
            self.pause_reasons.add(reason)
        self._sink.record_kill_switch_activation(reason)
        logger.critical("KILL SWITCH ACTIVATED: %s", reason)

        results: dict[str, Any] = {
            "status": "activated",
            "reason": reason,
            "cancelled_orders": [],
            "closed_positions": [],
            "errors": [],
        }

        # Step 1: Cancel all pending orders
        try:
            cancelled = await self._gateway.cancel_all_orders()
            results["cancelled_orders"] = cancelled
            logger.info("Cancelled %d orders", len(cancelled))
        except Exception as e:
            self._sink.record_kill_switch_step_failure("cancel_orders")
            # odyssey-review RP2 (SEC, CWE-532): the gateway re-raises raw CCXT
            # exceptions whose message may embed OKX apiKey/URL. This errors
            # list is returned through web/app.py json_response(result) to the
            # HTTP client, so scrub before it reaches log AND response.
            results["errors"].append(f"cancel_orders: {redact_secrets(str(e))}")
            logger.error("Failed to cancel orders: %s", redact_secrets(str(e)))

        # Step 2: Close all open positions with market orders.
        # Fail-closed (odyssey-improve SEC-H5): a failure from query_positions
        # means we CANNOT enumerate positions to close — report failure rather
        # than falsely reporting closed_positions=[]. Any exception (GatewayError
        # from a typed failure, or a legacy RuntimeError from a mock/test
        # gateway) is treated as "cannot verify positions" — the safe posture.
        positions: list[Any] = []
        try:
            positions = await self._gateway.query_positions()
        except Exception as e:
            self._sink.record_kill_switch_step_failure("query_positions")
            results["errors"].append(f"query_positions: {redact_secrets(str(e))}")
            results["status"] = "failed"
            logger.error(
                "Kill switch query_positions failed — positions may still be "
                "open; manual intervention required: %s",
                redact_secrets(str(e)),
            )
            return results

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
                        params=dict(_REDUCE_ONLY_PARAMS),
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
                    self._sink.record_kill_switch_step_failure(f"close_{pos.symbol}")
                    results["errors"].append(f"close_{pos.symbol}: {redact_secrets(str(e))}")
                    logger.error("Failed to close %s: %s", pos.symbol, redact_secrets(str(e)))

        # If any close failed, the system is in a partial/half-state — surface
        # it so the operator does not believe the stop completed cleanly.
        if results["errors"]:
            results["status"] = "partial"
            logger.error(
                "Kill switch activated with %d error(s) — residual positions "
                "may remain open; manual intervention required",
                len(results["errors"]),
            )

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
