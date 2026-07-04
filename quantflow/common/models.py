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

    @property
    def total_value(self) -> float:
        return self.cash + sum(p.market_value for p in self.positions.values())


@dataclass
class RiskDecision:
    passed: bool
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)
