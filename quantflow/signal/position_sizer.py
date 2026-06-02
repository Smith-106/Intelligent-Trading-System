"""Position sizing using half-Kelly criterion with signal strength scaling."""

from __future__ import annotations

import logging

from quantflow.common.models import Portfolio, Signal

logger = logging.getLogger(__name__)


class PositionSizer:
    """Half-Kelly position sizer with configurable constraints.

    Size = kelly_fraction * raw_kelly * signal.strength
    Clamped by position_limit_pct from risk config.
    """

    def __init__(
        self,
        method: str = "kelly",
        kelly_fraction: float = 0.5,
        fixed_pct: float = 0.10,
        max_position_pct: float = 0.20,
        min_order_notional: float = 10.0,
        fee_rate: float = 0.001,
    ) -> None:
        self._method = method
        self._kelly_fraction = kelly_fraction
        self._fixed_pct = fixed_pct
        self._max_position_pct = max_position_pct
        self._min_order_notional = min_order_notional
        self._fee_rate = fee_rate

    def size(
        self,
        signal: Signal,
        portfolio: Portfolio,
        win_rate: float = 0.5,
        win_loss_ratio: float = 2.0,
    ) -> float:
        """Return order notional value (quote currency).

        Scales by signal.strength and clamps by max_position_pct.
        Deducts existing position and estimated fees.
        """
        total_value = portfolio.total_value
        if total_value <= 0:
            return 0.0

        if self._method == "fixed":
            base = total_value * self._fixed_pct
        else:
            # Raw Kelly: f* = (p*b - q) / b
            p = max(0.01, min(win_rate, 0.99))
            q = 1.0 - p
            b = max(win_loss_ratio, 0.01)
            raw_kelly = (p * b - q) / b
            if raw_kelly <= 0:
                return 0.0
            base = total_value * self._kelly_fraction * raw_kelly

        # Scale by signal strength [0, 1]
        strength = max(0.0, min(signal.strength, 1.0))
        target = base * strength

        # Clamp to max position limit
        max_notional = total_value * self._max_position_pct
        target = min(target, max_notional)

        # Deduct existing position in same symbol
        pos = portfolio.positions.get(signal.symbol)
        if pos is not None:
            existing = abs(pos.quantity * pos.current_price)
            same_direction = (pos.quantity > 0 and signal.direction.value > 0) or (
                pos.quantity < 0 and signal.direction.value < 0
            )
            if same_direction:
                target = max(0.0, target - existing)

        # Subtract estimated round-trip fees
        fee_cost = target * self._fee_rate * 2
        target = max(0.0, target - fee_cost)

        # Skip tiny orders
        if target < self._min_order_notional:
            return 0.0

        return round(target, 2)
