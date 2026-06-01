"""Abstract gateway interface for exchange connectivity.

Defines the canonical interface that all gateways (OKX, Paper, etc.) must implement.
Matches the documented API: connect, send_order, cancel_order, query_positions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from quantflow.common.models import Order, Position


class GatewayBase(ABC):
    """Base class for all trading gateways.

    Subclasses must implement: connect, send_order, cancel_order, query_positions.
    Optional overrides: disconnect, cancel_all_orders, subscribe.
    """

    @abstractmethod
    @abstractmethod
    async def connect(self, config: dict[str, Any] | None = None) -> None:
        """Connect to the exchange.

        Args:
            config: Exchange-specific configuration (API keys, sandbox mode, etc.).
        """

    @abstractmethod
    @abstractmethod
    async def send_order(self, order: Order) -> str:
        """Send an order to the exchange.

        Args:
            order: Order object with symbol, side, type, quantity, price.

        Returns:
            Exchange-assigned order ID as string.
        """

    @abstractmethod
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
    @abstractmethod
    async def query_positions(self) -> list[Position]:
        """Query all open positions.

        Returns:
            List of Position objects for all open positions.
        """

    async def disconnect(self) -> None:
        """Disconnect from the exchange. Override if cleanup needed."""

    async def cancel_all_orders(self, symbol: str | None = None) -> list[bool]:
        """Cancel all open orders, optionally filtered by symbol.

        Returns:
            List of cancellation results.
        """
        return []

    async def subscribe(self, channel: str, callback: Any = None) -> None:
        """Subscribe to a market data channel. Override for WebSocket support."""
