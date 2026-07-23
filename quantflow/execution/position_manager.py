"""Position manager — track open positions and mark-to-market."""

from __future__ import annotations

import logging

from quantflow.common.models import Position
from quantflow.common.validators import POSITION_EPSILON

logger = logging.getLogger(__name__)


class PositionManager:
    """Track open positions with real-time P&L calculation."""

    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}

    def update_market_price(self, symbol: str, price: float) -> None:
        """Update mark-to-market price for a position and recalculate unrealized P&L."""
        pos = self._positions.get(symbol)
        if pos is not None:
            unrealized = (price - pos.entry_price) * pos.quantity
            self._positions[symbol] = Position(
                symbol=symbol,
                quantity=pos.quantity,
                entry_price=pos.entry_price,
                current_price=price,
                unrealized_pnl=unrealized,
                strategy_id=pos.strategy_id,
            )

    def update_position(
        self,
        symbol: str,
        quantity_delta: float,
        price: float,
        *,
        strategy_id: str = "",
    ) -> None:
        """Update position after a fill. Negative delta reduces position."""
        existing = self._positions.get(symbol)
        if existing is None:
            if abs(quantity_delta) < POSITION_EPSILON:
                return
            self._positions[symbol] = Position(
                symbol=symbol,
                quantity=quantity_delta,
                entry_price=price,
                current_price=price,
                unrealized_pnl=0.0,
                strategy_id=strategy_id,
            )
            return

        new_qty = existing.quantity + quantity_delta
        if abs(new_qty) < POSITION_EPSILON:
            # Position closed
            del self._positions[symbol]
            logger.info("Position closed: %s", symbol)
            return

        # Weighted average entry price (only on increase)
        if (quantity_delta > 0 and existing.quantity > 0) or (
            quantity_delta < 0 and existing.quantity < 0
        ):
            # Increasing position in same direction
            total_cost = existing.entry_price * abs(existing.quantity) + price * abs(quantity_delta)
            total_qty = abs(new_qty)
            avg_price = total_cost / total_qty
        elif existing.quantity * new_qty < 0:
            # Position flipped direction — the new leg starts at the fill price.
            # Keeping the old entry_price would invert P&L on the new short/long.
            avg_price = price
        else:
            # Reducing position in same direction — keep entry price
            avg_price = existing.entry_price

        self._positions[symbol] = Position(
            symbol=symbol,
            quantity=new_qty,
            entry_price=avg_price,
            current_price=price,
            unrealized_pnl=(price - avg_price) * new_qty,
            strategy_id=existing.strategy_id or strategy_id,
        )

    def get_position(self, symbol: str) -> Position | None:
        return self._positions.get(symbol)

    def get_all_positions(self) -> list[Position]:
        return list(self._positions.values())

    def has_position(self, symbol: str) -> bool:
        return (
            symbol in self._positions and abs(self._positions[symbol].quantity) > POSITION_EPSILON
        )

    def close_position(self, symbol: str) -> Position | None:
        """Remove and return a position (used when fully closed)."""
        return self._positions.pop(symbol, None)

    @property
    def position_count(self) -> int:
        return len(self._positions)

    @property
    def total_unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self._positions.values())

    @property
    def total_market_value(self) -> float:
        return sum(p.market_value for p in self._positions.values())
