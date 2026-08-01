"""Core data models for the QuantFlow trading system."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any


class Direction(IntEnum):
    LONG = 1
    FLAT = 0
    SHORT = -1


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(StrEnum):
    CREATED = "created"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class RunMode(StrEnum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


# --- Event Types (constants) ---

EVENT_BAR = "bar"
EVENT_TICK = "tick"
EVENT_SIGNAL = "signal"
EVENT_ORDER = "order"
EVENT_FILL = "fill"
EVENT_RISK = "risk"


@dataclass
class Bar:
    symbol: str
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    symbol: str
    direction: Direction
    strength: float = 1.0
    price: float = 0.0
    strategy_id: str = ""
    timestamp: int = 0


def strategy_id_constituents(strategy_id: str) -> list[str]:
    """Split a (possibly compound) ``strategy_id`` into its constituents.

    A consolidated signal carries a comma-joined ``strategy_id`` such as
    ``"momentum_rotation,trend_following"``. Downstream risk budget / win-rate
    lookups key on a single strategy id, so they must expand the compound key
    rather than miss the lookup entirely (which would bypass per-strategy risk
    budgets for consolidated signals).
    """
    if not strategy_id:
        return []
    return [part for part in (s.strip() for s in strategy_id.split(",")) if part]


@dataclass
class Position:
    symbol: str
    quantity: float
    entry_price: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    strategy_id: str = ""

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def side(self) -> Direction:
        if self.quantity > 0:
            return Direction.LONG
        elif self.quantity < 0:
            return Direction.SHORT
        return Direction.FLAT

    def with_current_price(self, price: float) -> Position:
        """Return a copy of this position with ``current_price`` updated and
        ``unrealized_pnl`` recomputed from the single canonical formula.

        ISS-20260723-002: the unrealized-PnL formula
        ``(price - entry_price) * quantity`` was duplicated in
        ``PortfolioManager._merge_or_replace`` (signal/portfolio.py) and
        ``PaperGateway.update_market_price`` (execution/paper_gateway.py),
        risking silent divergence. Centralizing it here gives one owner;
        both call sites now route through this helper.
        """
        return Position(
            symbol=self.symbol,
            quantity=self.quantity,
            entry_price=self.entry_price,
            current_price=price,
            unrealized_pnl=(price - self.entry_price) * self.quantity,
            strategy_id=self.strategy_id,
        )


@dataclass
class OrderRequest:
    symbol: str
    side: OrderSide
    order_type: str = "market"
    quantity: float = 0.0
    price: float | None = None
    strategy_id: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Order:
    order_id: str
    symbol: str
    side: OrderSide
    order_type: str
    quantity: float
    price: float | None = None
    status: OrderStatus = OrderStatus.CREATED
    filled_quantity: float = 0.0
    filled_price: float = 0.0
    fee: float = 0.0
    strategy_id: str = ""
    created_at: float = 0.0
    # ISS-20260720-004 Wave 4: cumulative-fill contract. ccxt/OKX report
    # ``filled`` as a cumulative total, not a per-callback delta. To update L4
    # incrementally without double-counting, OrderManager tracks how much of
    # the cumulative fill has already been applied to the book here; the next
    # delta = filled_quantity - applied_filled_qty.
    applied_filled_qty: float = 0.0
    # Exchange-specific params forwarded to the gateway (e.g.
    # {"reduceOnly": True} — CCXT's canonical camelCase param — for FLAT close
    # orders). Opaque to the engine.
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderResult:
    order_id: str = ""
    status: OrderStatus = OrderStatus.CREATED
    symbol: str = ""
    side: str = ""
    filled_quantity: float = 0.0
    average_price: float = 0.0
    fee: float = 0.0
    error: str = ""


@dataclass
class Portfolio:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    current_drawdown: float = 0.0
    # Cumulative realized PnL from closed legs (ISS-20260720-004 Wave 1):
    # flip/partial-close attributes the closing leg's PnL here instead of
    # letting it stay implicit in cash. Defaults preserve backward compat.
    realized_pnl: float = 0.0
    # Daily-loss baseline (ISS-20260720-004 Wave 3): the equity anchored at the
    # first bar of the calendar day. <=0 means "not anchored yet" (warmup).
    daily_baseline: float = 0.0
    # M4-5.3: total pending exposure (reserved notional awaiting fill confirmation).
    pending_exposure: float = 0.0

    @property
    def total_value(self) -> float:
        return self.cash + sum(p.market_value for p in self.positions.values())


@dataclass
class RiskDecision:
    passed: bool
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)
