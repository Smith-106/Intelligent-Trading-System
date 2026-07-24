"""Position sizing using half-Kelly criterion with signal strength scaling."""

from __future__ import annotations

import logging
import math
import statistics
from collections import deque

from quantflow.common.models import Portfolio, Signal, strategy_id_constituents

logger = logging.getLogger(__name__)


class PositionSizer:
    """Half-Kelly position sizer with configurable constraints.

    Size = kelly_fraction * raw_kelly * signal.strength
    Clamped by position_limit_pct from risk config.

    Optional vol-targeting (deep-research F3 / P1): when ``vol_target_pct``
    is set, the notional is additionally bounded by
    ``min(half-Kelly, vol-target, single-name cap)``. Vol-target scales
    exposure inversely to realized volatility so the strategy's contribution
    to portfolio volatility stays near the target. OFF by default (None) to
    preserve the byte-for-byte backtest baseline.
    """

    def __init__(
        self,
        method: str = "kelly",
        kelly_fraction: float = 0.5,
        fixed_pct: float = 0.10,
        max_position_pct: float = 0.20,
        min_order_notional: float = 10.0,
        fee_rate: float = 0.001,
        vol_target_pct: float | None = None,
        vol_annualization: int = 365,
        vol_window: int = 30,
    ) -> None:
        self._method = method
        self._kelly_fraction = kelly_fraction
        self._fixed_pct = fixed_pct
        self._max_position_pct = max_position_pct
        self._min_order_notional = min_order_notional
        self._fee_rate = fee_rate
        self._vol_target_pct = vol_target_pct
        self._vol_annualization = vol_annualization
        self._vol_window = vol_window
        self._returns_history: deque[float] = deque(maxlen=max(vol_window, 2))

    def add_return(self, ret: float) -> None:
        """Feed a realized bar return for volatility-targeting estimation.

        No-op effect on sizing when vol-targeting is OFF (the default); only
        consulted when ``vol_target_pct`` is set. Mirrors RiskEngine.add_return.
        """
        self._returns_history.append(ret)

    def reset(self) -> None:
        """Clear the returns history so a restarted session's vol-target
        estimate is not biased by the previous run's returns (CORR-M2).
        Mirrors RiskEngine.reset.
        """
        self._returns_history.clear()

    def _realized_vol(self) -> float | None:
        """Annualized realized volatility from recent returns, or None.

        Returns None when vol-targeting is OFF or insufficient history
        (< vol_window bars), so the caller falls back to the Kelly target.
        """
        if self._vol_target_pct is None:
            return None
        # Need at least vol_window bars of history so the realized-vol estimate
        # is stable; the previous guard (<2) let sizing fire with as few as 2
        # bars, producing a wildly volatile sigma that over-traded on the
        # first handful of bars after warmup.
        if len(self._returns_history) < self._vol_window:
            return None
        values = [float(x) for x in self._returns_history if not math.isnan(x)]
        if len(values) < 2:
            return None
        sigma = statistics.stdev(values)
        # float() wraps the product: statistics.stdev is typed as Any under
        # strict checking, so the bare product would propagate Any.
        return float(sigma * (self._vol_annualization**0.5))

    def _vol_target_notional(self, total_value: float) -> float | None:
        """Max notional implied by the volatility target, or None if N/A.

        vol_target_notional = total_value * vol_target_pct / realized_vol,
        i.e. scale exposure down in high-vol regimes and up in low-vol
        regimes so realized portfolio vol tracks the target.
        """
        realized = self._realized_vol()
        if realized is None or realized <= 0:
            return None
        target_pct = self._vol_target_pct
        assert target_pct is not None  # guarded by _realized_vol() returning None when OFF
        return float(total_value * target_pct / realized)

    def size(
        self,
        signal: Signal,
        portfolio: Portfolio,
        win_rate: float = 0.5,
        win_loss_ratio: float = 2.0,
        strategy_win_rates: dict[str, float] | None = None,
        allocation: float = 1.0,
    ) -> float:
        """Return order notional value (quote currency).

        Scales by signal.strength and clamps by max_position_pct.
        When vol-targeting is enabled, additionally clamps by the
        vol-target notional (min of half-Kelly, vol-target, single-name cap).
        Deducts existing position and estimated fees.

        ``allocation`` is the strategy's portfolio weight (summed across
        compound strategy_id constituents). It is applied BEFORE the cap and
        deduction so the cap always clamps the FINAL notional — a compound
        signal whose constituents sum > 1 cannot inflate the order past
        max_position_pct (ISS-038). The prior call site multiplied by
        allocation AFTER size() returned, re-inflating an already-capped
        target.
        """
        total_value = portfolio.total_value
        if total_value <= 0:
            return 0.0

        # Use per-strategy win_rate when available. A consolidated signal
        # carries a compound strategy_id; average the win rates of its
        # constituents so sizing reflects the blended edge rather than the
        # default (which would over-size when one constituent is strong).
        rates = strategy_win_rates or {}
        constituents = strategy_id_constituents(signal.strategy_id) or [signal.strategy_id]
        matched = [rates[c] for c in constituents if c in rates]
        actual_win_rate = sum(matched) / len(matched) if matched else win_rate

        if self._method == "fixed":
            base = total_value * self._fixed_pct
        else:
            # Raw Kelly: f* = (p*b - q) / b
            p = max(0.01, min(actual_win_rate, 0.99))
            q = 1.0 - p
            b = max(win_loss_ratio, 0.01)
            raw_kelly = (p * b - q) / b
            if raw_kelly <= 0:
                return 0.0
            base = total_value * self._kelly_fraction * raw_kelly

        # Scale by signal strength [0, 1] and strategy allocation weight.
        # Allocation is applied here (before the cap + deduction) so the cap
        # clamps the final notional even when a compound strategy_id sums > 1.
        strength = max(0.0, min(signal.strength, 1.0))
        allocation = max(0.0, allocation)
        target = base * strength * allocation

        # Vol-target cap (opt-in): min(half-Kelly, vol-target, single-name cap).
        # When OFF or insufficient history, this is a no-op (None).
        vol_cap = self._vol_target_notional(total_value)
        if vol_cap is not None:
            target = min(target, vol_cap)

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
