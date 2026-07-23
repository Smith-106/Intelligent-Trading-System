"""Abstract gateway interface for exchange connectivity.

Defines the canonical interface that all gateways (OKX, Paper, etc.) must implement.
Matches the documented API: connect, send_order, cancel_order, query_positions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from quantflow.common.models import Order, Position


class GatewayError(RuntimeError):
    """Typed failure for a gateway operation (odyssey-improve SEC-H5/REL-H2).

    Distinct from a benign empty result: a ``GatewayError`` means the gateway
    could not complete the request (reconnect failed, query timed out, parse
    error). Callers that MUST know the difference — notably KillSwitch —
    branch on this instead of silently treating ``[]`` as "no positions",
    which previously caused an emergency stop to report success while real
    positions stayed open on the exchange.
    """


class GatewayBase(ABC):
    """Base class for all trading gateways.

    Subclasses must implement: connect, send_order, cancel_order, query_positions.
    Optional overrides: disconnect, cancel_all_orders, update_market_price, subscribe.
    """

    @abstractmethod
    async def connect(self, config: dict[str, Any] | None = None) -> None:
        """Connect to the exchange.

        Args:
            config: Exchange-specific configuration (API keys, sandbox mode, etc.).
        """

    @abstractmethod
    async def send_order(self, order: Order) -> str:
        """Send an order to the exchange.

        Args:
            order: Order object with symbol, side, type, quantity, price.

        Returns:
            Exchange-assigned order ID as string.
        """

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an existing order.

        Args:
            order_id: Exchange order ID to cancel.
            symbol: Trading pair symbol (required by some exchanges).

        Returns:
            True if cancellation succeeded, False otherwise.
        """

    @abstractmethod
    async def query_positions(self) -> list[Position]:
        """Query all open positions.

        Raises ``GatewayError`` on failure (do not return ``[]`` to mean
        "query failed" — that is indistinguishable from a genuine empty
        result and breaks fail-closed callers like KillSwitch).

        Returns:
            List of Position objects for all open positions (empty if none).
        """

    async def disconnect(self) -> None:
        """Disconnect from the exchange. Override if cleanup needed."""

    async def cancel_all_orders(self, symbol: str | None = None) -> list[bool]:
        """Cancel all open orders, optionally filtered by symbol.

        Returns:
            List of cancellation results.
        """
        return []

    def update_market_price(self, symbol: str, price: float) -> None:
        """Push a mark-price update to the gateway (optional override).

        PaperGateway overrides this to revalue its local book; OKXGateway
        leaves it as a no-op (live mark prices come from the exchange feed).
        Declared on the base (odyssey-improve ARCH-M2) so ExecutionEngine
        calls it directly instead of getattr/callable duck-typing past the
        interface, which broke live/paper parity for gateway-side marks.
        """

    async def subscribe(self, channel: str, callback: Any = None) -> None:
        """Subscribe to a market data channel. Override for WebSocket support."""
