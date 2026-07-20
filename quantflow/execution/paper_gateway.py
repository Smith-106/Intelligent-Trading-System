"""Paper Gateway — local simulated exchange for paper trading."""

from __future__ import annotations

import logging
from typing import Any

from quantflow.common.models import Order, OrderStatus, Position
from quantflow.execution.gateway_base import GatewayBase

logger = logging.getLogger(__name__)


class PaperGateway(GatewayBase):
    """Simulated gateway for paper trading with slippage and fees.

    Orders are filled immediately at the current price plus slippage.
    Suitable for strategy validation before going live.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self._slippage = cfg.get("slippage", 0.001)
        self._maker_fee = cfg.get("maker_fee", 0.0008)
        self._taker_fee = cfg.get("taker_fee", 0.001)
        self._initial_capital = cfg.get("initial_capital", 1_000_000.0)
        self._cash = self._initial_capital
        self._positions: dict[str, Position] = {}
        self._order_counter = 0
        self._prices: dict[str, float] = {}  # symbol → last known price

    async def connect(self, config: dict[str, Any] | None = None) -> None:
        self._cash = self._initial_capital
        self._positions.clear()
        logger.info(
            "PaperGateway connected: capital=$%.2f, slippage=%.4f, taker_fee=%.4f",
            self._cash,
            self._slippage,
            self._taker_fee,
        )

    async def disconnect(self) -> None:
        logger.info("PaperGateway disconnected. Final equity: $%.2f", self._equity())

    async def send_order(self, order: Order) -> str:
        """Simulate order fill with slippage and fees."""
        self._order_counter += 1
        order_id = f"paper-{self._order_counter}"

        symbol = order.symbol
        side = order.side.value
        quantity = order.quantity
        price = order.price

        fill_price = price or self._prices.get(symbol, 0.0)
        if fill_price <= 0:
            order.status = OrderStatus.REJECTED
            order.order_id = order_id
            return order_id

        # Apply slippage
        slip_mult = 1 + self._slippage if side == "buy" else 1 - self._slippage
        fill_price *= slip_mult

        # Calculate fees
        notional = fill_price * quantity
        fee = notional * self._taker_fee

        # Update cash
        # NOTE: PaperGateway maintains its own cash/position book for the gateway
        # contract (query_positions, _equity for kill-switch). This is a THIRD
        # source of truth alongside L4 PortfolioManager and L5 PositionManager.
        # The SELL branch (notional - fee) is numerically equivalent to L4's
        # (_cash += notional; _cash -= fee), so the fee-credit formula does not
        # drift in value — but the structural divergence (no reconcile between
        # the three books) is tracked as ARCH-H2/ARCH-M5 (issue: L4/L5/gateway
        # position-state reconciliation). PaperGateway is intentionally a pure
        # fill simulator here; L4 remains authoritative for risk decisions.
        if side == "buy":
            self._cash -= notional + fee
        else:
            self._cash += notional - fee

        # Update position
        self._update_position(
            symbol,
            quantity if side == "buy" else -quantity,
            fill_price,
            strategy_id=order.strategy_id,
        )
        self._prices[symbol] = fill_price

        logger.info(
            "Paper fill: %s %s %.6f @ %.2f (fee=%.2f)", side, symbol, quantity, fill_price, fee
        )

        order.order_id = order_id
        order.status = OrderStatus.FILLED
        order.filled_quantity = quantity
        order.filled_price = fill_price
        order.fee = fee
        return order_id

    async def cancel_order(self, order_id: str, symbol: str = "") -> bool:
        # Paper orders fill instantly — nothing to cancel
        logger.debug("Paper cancel: %s (orders fill instantly, nothing to cancel)", order_id)
        return True

    async def cancel_all_orders(self, symbol: str | None = None) -> list[bool]:
        return []

    async def query_positions(self) -> list[Position]:
        return list(self._positions.values())

    def update_price(self, symbol: str, price: float) -> None:
        """Update last known price for a symbol (called by data feed)."""
        self._prices[symbol] = price
        pos = self._positions.get(symbol)
        if pos is not None:
            self._positions[symbol] = Position(
                symbol=symbol,
                quantity=pos.quantity,
                entry_price=pos.entry_price,
                current_price=price,
                unrealized_pnl=(price - pos.entry_price) * pos.quantity,
                strategy_id=pos.strategy_id,
            )

    def _update_position(
        self, symbol: str, quantity: float, price: float, *, strategy_id: str = ""
    ) -> None:
        existing = self._positions.get(symbol)
        if existing is None:
            if abs(quantity) < 1e-10:
                return
            self._positions[symbol] = Position(
                symbol=symbol,
                quantity=quantity,
                entry_price=price,
                current_price=price,
                unrealized_pnl=0.0,
                strategy_id=strategy_id,
            )
            return

        new_qty = existing.quantity + quantity
        if abs(new_qty) < 1e-10:
            del self._positions[symbol]
            return

        # Update average entry price (when adding to position)
        if (quantity > 0 and existing.quantity > 0) or (quantity < 0 and existing.quantity < 0):
            total_cost = existing.entry_price * abs(existing.quantity) + price * abs(quantity)
            avg_price = total_cost / abs(new_qty)
        elif existing.quantity * new_qty < 0:
            # Position flipped direction — new leg starts at the fill price so
            # P&L is not inverted on the new short/long.
            avg_price = price
        else:
            avg_price = existing.entry_price

        self._positions[symbol] = Position(
            symbol=symbol,
            quantity=new_qty,
            entry_price=avg_price,
            current_price=price,
            unrealized_pnl=(price - avg_price) * new_qty,
            strategy_id=existing.strategy_id or strategy_id,
        )

    def _equity(self) -> float:
        pos_value = sum(p.quantity * p.current_price for p in self._positions.values())
        return float(self._cash + pos_value)

    @property
    def is_connected(self) -> bool:
        return True
