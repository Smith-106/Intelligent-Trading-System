"""Portfolio manager — position tracking, mark-to-market, and drawdown monitoring."""

from __future__ import annotations

import logging
from typing import Any

from quantflow.common.models import Portfolio, Position

logger = logging.getLogger(__name__)


class PortfolioManager:
    """Track portfolio positions, equity, and drawdown.

    Supports mark-to-market valuation, unrealized P&L calculation,
    and peak/drawdown tracking for risk engine integration.
    """

    def __init__(self, initial_capital: float = 100000.0) -> None:
        self._initial_capital = initial_capital
        self._cash = initial_capital
        self._positions: dict[str, Position] = {}
        self._peak_equity = initial_capital
        self._current_drawdown = 0.0
        self._allocation: dict[str, float] = {}

    # --- Core properties ---

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def current_drawdown(self) -> float:
        return self._current_drawdown

    @property
    def positions(self) -> dict[str, Position]:
        return self._positions

    @property
    def equity(self) -> float:
        """Total portfolio equity (cash + position market values)."""
        return self.total_value

    @property
    def portfolio(self) -> Portfolio:
        """Return a Portfolio model snapshot."""
        return Portfolio(
            cash=self._cash,
            positions=dict(self._positions),
            current_drawdown=self._current_drawdown,
        )

    @property
    def total_value(self) -> float:
        """Cash + sum of position market values."""
        pos_value = sum(p.market_value for p in self._positions.values())
        return self._cash + pos_value

    # --- Position management ---

    def get_position(self, symbol: str) -> Position | None:
        """Get position for a symbol, or None if not held."""
        return self._positions.get(symbol)

    def has_position(self, symbol: str) -> bool:
        """Check if a position exists for the symbol."""
        pos = self._positions.get(symbol)
        return pos is not None and abs(pos.quantity) > 1e-10

    def update_position(
        self,
        symbol: str,
        quantity_delta: float,
        price: float,
        *,
        fee: float = 0.0,
        strategy_id: str = "",
    ) -> None:
        """Update or create a position after a fill."""
        existing = self._positions.get(symbol)
        if abs(quantity_delta) < 1e-10:
            if existing is None:
                self._refresh_drawdown()
                return
            self._positions[symbol] = Position(
                symbol=symbol,
                quantity=existing.quantity,
                entry_price=existing.entry_price,
                current_price=price,
                unrealized_pnl=(price - existing.entry_price) * existing.quantity,
                strategy_id=existing.strategy_id,
            )
            self._refresh_drawdown()
            return

        # Cash follows trade notional directly; fee always reduces equity.
        self._cash -= quantity_delta * price
        if fee:
            self._cash -= fee

        if existing is None:
            self._positions[symbol] = Position(
                symbol=symbol,
                quantity=quantity_delta,
                entry_price=price,
                current_price=price,
                unrealized_pnl=0.0,
                strategy_id=strategy_id,
            )
            self._refresh_drawdown()
            return

        new_qty = existing.quantity + quantity_delta
        if abs(new_qty) < 1e-10:
            del self._positions[symbol]
            self._refresh_drawdown()
            return

        if existing.quantity * quantity_delta > 0:
            total_cost = (
                existing.entry_price * abs(existing.quantity)
                + price * abs(quantity_delta)
            )
            avg_price = total_cost / abs(new_qty)
        else:
            avg_price = price if existing.quantity * new_qty < 0 else existing.entry_price

        upnl = (price - avg_price) * new_qty
        self._positions[symbol] = Position(
            symbol=symbol,
            quantity=new_qty,
            entry_price=avg_price,
            current_price=price,
            unrealized_pnl=upnl,
            strategy_id=existing.strategy_id or strategy_id,
        )
        self._refresh_drawdown()

    # --- Mark-to-market ---

    def update_market_prices(self, prices: dict[str, float]) -> None:
        """Batch-update market prices for all held positions and recalculate P&L."""
        for symbol, price in prices.items():
            pos = self._positions.get(symbol)
            if pos is not None:
                upnl = (price - pos.entry_price) * pos.quantity
                self._positions[symbol] = Position(
                    symbol=symbol,
                    quantity=pos.quantity,
                    entry_price=pos.entry_price,
                    current_price=price,
                    unrealized_pnl=upnl,
                    strategy_id=pos.strategy_id,
                )

    def mark_to_market(self, price_feed: dict[str, float]) -> dict[str, float]:
        """Mark all positions to market and return unrealized P&L per symbol."""
        self.update_market_prices(price_feed)
        pnl = {s: p.unrealized_pnl for s, p in self._positions.items()}
        self._refresh_drawdown()
        return pnl

    def total_unrealized_pnl(self) -> float:
        """Sum of unrealized P&L across all positions."""
        return sum(p.unrealized_pnl for p in self._positions.values())

    # --- Cash and allocation ---

    def update_cash(self, amount: float) -> None:
        """Adjust cash balance by amount (positive=deposit, negative=withdrawal)."""
        self._cash += amount
        self._refresh_drawdown()

    def set_capital_baseline(self, capital: float) -> None:
        """Reset the initial-capital and peak-equity baseline atomically.

        Used when a session is started with an operator-supplied capital so
        that drawdown is measured against the correct base. Replaces direct
        mutation of private attributes from presentation layers.
        """
        self._initial_capital = capital
        self._peak_equity = max(capital, self.total_value)
        self._current_drawdown = 0.0

    def set_allocation(self, allocation: dict[str, float]) -> None:
        """Set target allocation weights per strategy."""
        self._allocation = allocation

    def get_strategy_allocation(self, strategy_id: str) -> float:
        """Get allocation weight for a strategy, or 0 if not set."""
        return self._allocation.get(strategy_id, 0.0)

    @property
    def allocation(self) -> dict[str, float]:
        return self._allocation

    # --- Risk checks ---

    def check_drawdown(self, max_drawdown: float) -> bool:
        """Check if current drawdown is within the allowed limit.

        Args:
            max_drawdown: Maximum allowed drawdown (negative, e.g. -0.10 for 10%).

        Returns:
            True if drawdown is within limits, False if breached.
        """
        return self._current_drawdown > max_drawdown

    def snapshot(self) -> dict[str, Any]:
        """Return a snapshot of portfolio state."""
        return {
            "cash": self._cash,
            "total_value": self.total_value,
            "equity": self.equity,
            "positions": len(self._positions),
            "drawdown": self._current_drawdown,
            "peak_equity": self._peak_equity,
        }

    def _refresh_drawdown(self) -> None:
        total = self.total_value
        if total > self._peak_equity:
            self._peak_equity = total
        if self._peak_equity > 0:
            self._current_drawdown = (total - self._peak_equity) / self._peak_equity
