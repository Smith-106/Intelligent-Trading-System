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
        reference_multiplier: float = 1.0,
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

        ``reference_multiplier`` is an optional external scale (e.g. KOL
        consensus reference weight). Default 1.0 = no change. Applied after
        strength*allocation and still subject to max_position / vol caps.
        Never flips direction — callers must not encode side in this factor.
        """
        total_value = portfolio.total_value
        if total_value <= 0:
            return 0.0

        actual_win_rate = self._blend_win_rate(signal, win_rate, strategy_win_rates)

        if self._method == "fixed":
            base = total_value * self._fixed_pct
        elif self._method == "risk_parity":
            # s5 (T-s5-02): weight-driven sizing. The portfolio-level
            # risk-parity weight is carried by ``allocation`` (engine passes
            # the strategy's allocation weight into size()); base = total
            # value so ``target = base * strength * allocation`` yields
            # ``total_value * strength * weight`` — the risk-parity notional.
            base = total_value
        else:
            base = self._kelly_base_notional(total_value, actual_win_rate, win_loss_ratio)

        # Scale by signal strength [0, 1] and strategy allocation weight.
        # Allocation is applied here (before the cap + deduction) so the cap
        # clamps the final notional even when a compound strategy_id sums > 1.
        strength = max(0.0, min(signal.strength, 1.0))
        allocation = max(0.0, allocation)
        ref_m = max(0.0, float(reference_multiplier))
        target = base * strength * allocation * ref_m

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

    def _blend_win_rate(
        self,
        signal: Signal,
        default_win_rate: float,
        strategy_win_rates: dict[str, float] | None,
    ) -> float:
        """Blend per-strategy win rates across a (possibly compound) strategy_id.

        ISS-20260723-006: extracted from ``size``. A consolidated signal carries
        a comma-joined strategy_id; average the win rates of its constituents so
        sizing reflects the blended edge rather than the default (which would
        over-size when one constituent is strong). Falls back to the default
        win_rate when no per-strategy rate is available.
        """
        rates = strategy_win_rates or {}
        constituents = strategy_id_constituents(signal.strategy_id) or [signal.strategy_id]
        matched = [rates[c] for c in constituents if c in rates]
        return sum(matched) / len(matched) if matched else default_win_rate

    def _kelly_base_notional(
        self, total_value: float, win_rate: float, win_loss_ratio: float
    ) -> float:
        """Kelly-fraction base notional, or 0.0 if the raw Kelly fraction <= 0.

        ISS-20260723-006: extracted from ``size``. Raw Kelly f* = (p*b - q)/b,
        clamped to a sane [0.01, 0.99] win-rate window; scaled by the configured
        ``_kelly_fraction``. Returns 0.0 (caller short-circuits to no order)
        when the edge is non-positive.
        """
        p = max(0.01, min(win_rate, 0.99))
        q = 1.0 - p
        b = max(win_loss_ratio, 0.01)
        raw_kelly = (p * b - q) / b
        if raw_kelly <= 0:
            return 0.0
        return total_value * self._kelly_fraction * raw_kelly
