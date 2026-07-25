"""Position manager — thin delegate to L4 PortfolioManager (ISS-20260720-004 Wave 2).

Previously PositionManager maintained its own ``_positions`` book — a second
source of truth alongside L4 PortfolioManager and PaperGateway's third book.
The three diverged on paper fills (each updated its own), on sync_positions
(only L5 was written), on partial fills (PARTIAL never reached position
update), and on flips (realized PnL was implicit in cash). Wave 2 retires
this class to a thin route over the single L4 authoritative book.

When ExecutionEngine is constructed without a portfolio (tests, standalone),
PositionManager creates a default PortfolioManager so the public API stays
usable; TradingSession injects the shared portfolio via
ExecutionEngine.set_portfolio so submit()'s L4 updates land on the same
instance ``_process_signal`` reads.
"""

from __future__ import annotations

import logging

from quantflow.common.models import Position
from quantflow.signal.portfolio import PortfolioManager

logger = logging.getLogger(__name__)


class PositionManager:
    """Thin delegate over L4 PortfolioManager (the authoritative book)."""

    def __init__(self, portfolio: PortfolioManager | None = None) -> None:
        # Default to a private L4 instance so standalone/test usage (no
        # TradingSession injection) still works; production injects the shared
        # portfolio via bind_portfolio so submit()'s updates land on the same
        # book _process_signal reads.
        self._portfolio = portfolio if portfolio is not None else PortfolioManager()

    def bind_portfolio(self, portfolio: PortfolioManager) -> None:
        """Rebind to the shared L4 portfolio (called by ExecutionEngine.set_portfolio)."""
        self._portfolio = portfolio

    def update_market_price(self, symbol: str, price: float) -> None:
        """Update mark-to-market price for a position (delegate to L4 batch mark)."""
        self._portfolio.update_market_prices({symbol: price})

    def update_position(
        self,
        symbol: str,
        quantity_delta: float,
        price: float,
        *,
        fee: float = 0.0,
        strategy_id: str = "",
    ) -> None:
        """Update position after a fill (delegate to L4, including fee)."""
        self._portfolio.update_position(
            symbol, quantity_delta, price, fee=fee, strategy_id=strategy_id
        )

    def set_position(self, symbol: str, position: Position) -> None:
        """Overwrite a position from an exchange sync (delegate to L4)."""
        self._portfolio.set_position(symbol, position)

    def get_position(self, symbol: str) -> Position | None:
        return self._portfolio.get_position(symbol)

    def get_all_positions(self) -> list[Position]:
        return list(self._portfolio.positions.values())

    def has_position(self, symbol: str) -> bool:
        return self._portfolio.has_position(symbol)

    def close_position(self, symbol: str) -> Position | None:
        """Remove and return a position (used when fully closed).

        Delegate to L4 by submitting the opposing delta at the position's last
        mark price — L4's update_position deletes the entry on full close.
        """
        pos = self._portfolio.get_position(symbol)
        if pos is None:
            return None
        price = pos.current_price if pos.current_price > 0 else pos.entry_price
        self._portfolio.update_position(symbol, -pos.quantity, price)
        return pos

    @property
    def position_count(self) -> int:
        return len(self._portfolio.positions)

    @property
    def total_unrealized_pnl(self) -> float:
        return self._portfolio.total_unrealized_pnl()

    @property
    def total_market_value(self) -> float:
        return sum(p.market_value for p in self._portfolio.positions.values())
