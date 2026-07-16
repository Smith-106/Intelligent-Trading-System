"""Scaling position sizer — Liu Yudong progressive position model.

Implements progressive position building (试仓→加仓→追仓) and
staged exit (30%→30%→40%). Outputs PositionRequest for RiskEngine
final authorization (G-003).

Risk limits:
- Single trade risk: ≤2% of total capital
- Daily max loss: ≤5%
- Monthly max loss: ≤15%
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PositionPhase(StrEnum):
    TRIAL = "trial"  # 试仓 10-15%
    ADD = "add"  # 加仓 20-30%
    CHASE = "chase"  # 追仓 10-15%
    EXIT_FIRST = "exit_first"  # 第一出场 30%
    EXIT_SECOND = "exit_second"  # 第二出场 30%
    EXIT_FINAL = "exit_final"  # 第三出场 40%


@dataclass
class PositionRequest:
    """A position sizing request submitted to RiskEngine."""

    phase: PositionPhase
    size_pct: float  # Requested position as % of total capital
    entry_price: float
    stop_price: float
    target_price: float | None = None
    wave_label: int = 0
    risk_pct: float = 0.0  # Actual risk as % of total capital

    @property
    def risk_reward_ratio(self) -> float | None:
        if self.target_price is None or self.entry_price == self.stop_price:
            return None
        reward = abs(self.target_price - self.entry_price)
        risk = abs(self.entry_price - self.stop_price)
        return reward / risk if risk > 0 else None


@dataclass
class ScalingConfig:
    """Configuration for scaling position sizer."""

    trial_pct: float = 0.125  # 12.5% (mid of 10-15%)
    add_pct: float = 0.25  # 25% (mid of 20-30%)
    chase_pct: float = 0.125  # 12.5% (mid of 10-15%)
    max_position_pct: float = 0.55  # 55% (mid of 50-60%)
    exit_first_pct: float = 0.30
    exit_second_pct: float = 0.30
    exit_final_pct: float = 0.40
    single_risk_pct: float = 0.02  # 2%
    daily_loss_limit_pct: float = 0.05  # 5%
    monthly_loss_limit_pct: float = 0.15  # 15%
    min_risk_reward: float = 3.0  # Minimum R:R ratio


class ScalingPositionSizer:
    """Progressive position sizer implementing Liu Yudong's scaling model.

    Position building phases:
    1. Trial (试仓): 10-15% at W2/W4 pullback area
    2. Add (加仓): 20-30% on breakout + W3 confirmation
    3. Chase (追仓): 10-15% during W3 trend continuation

    Exit phases:
    1. First exit: 30% at first target (e.g. 1.618 extension)
    2. Second exit: 30% at second target or divergence signal
    3. Final exit: 40% on wave invalidation or stop

    All requests go through RiskEngine for final authorization (G-003).
    """

    def __init__(self, config: ScalingConfig | None = None):
        self.config = config or ScalingConfig()
        self._current_position_pct = 0.0
        self._current_cost = 0.0
        self._trailing_stop = 0.0

    def compute_trial_position(
        self,
        capital: float,
        entry_price: float,
        stop_price: float,
        wave_label: int = 0,
    ) -> PositionRequest:
        """Compute trial (试仓) position size at W2/W4 pullback.

        Position = (capital x 2%) / (entry - stop)
        Capped at trial_pct of capital.
        """
        risk_amount = capital * self.config.single_risk_pct
        risk_per_unit = abs(entry_price - stop_price)

        if risk_per_unit <= 0:
            return PositionRequest(
                phase=PositionPhase.TRIAL,
                size_pct=0,
                entry_price=entry_price,
                stop_price=stop_price,
                wave_label=wave_label,
                risk_pct=0,
            )

        position_value = risk_amount / risk_per_unit * entry_price
        size_pct = min(position_value / capital, self.config.trial_pct)

        actual_risk = size_pct * capital * risk_per_unit / entry_price / capital

        return PositionRequest(
            phase=PositionPhase.TRIAL,
            size_pct=size_pct,
            entry_price=entry_price,
            stop_price=stop_price,
            wave_label=wave_label,
            risk_pct=actual_risk,
        )

    def compute_add_position(
        self,
        capital: float,
        entry_price: float,
        stop_price: float,
        wave_label: int = 0,
    ) -> PositionRequest:
        """Compute add (加仓) position size on W3 breakout confirmation."""
        risk_amount = capital * self.config.single_risk_pct
        risk_per_unit = abs(entry_price - stop_price)

        if risk_per_unit <= 0:
            return PositionRequest(
                phase=PositionPhase.ADD,
                size_pct=0,
                entry_price=entry_price,
                stop_price=stop_price,
                wave_label=wave_label,
                risk_pct=0,
            )

        position_value = risk_amount / risk_per_unit * entry_price
        remaining = max(0.0, self.config.max_position_pct - self._current_position_pct)
        size_pct = min(position_value / capital, self.config.add_pct, remaining)

        actual_risk = size_pct * capital * risk_per_unit / entry_price / capital

        return PositionRequest(
            phase=PositionPhase.ADD,
            size_pct=size_pct,
            entry_price=entry_price,
            stop_price=stop_price,
            wave_label=wave_label,
            risk_pct=actual_risk,
        )

    def compute_chase_position(
        self,
        capital: float,
        entry_price: float,
        stop_price: float,
        wave_label: int = 0,
    ) -> PositionRequest:
        """Compute chase (追仓) position during W3 trend continuation."""
        risk_amount = capital * self.config.single_risk_pct
        risk_per_unit = abs(entry_price - stop_price)

        if risk_per_unit <= 0:
            return PositionRequest(
                phase=PositionPhase.CHASE,
                size_pct=0,
                entry_price=entry_price,
                stop_price=stop_price,
                wave_label=wave_label,
                risk_pct=0,
            )

        position_value = risk_amount / risk_per_unit * entry_price
        remaining = max(0.0, self.config.max_position_pct - self._current_position_pct)
        size_pct = min(position_value / capital, self.config.chase_pct, remaining)

        return PositionRequest(
            phase=PositionPhase.CHASE,
            size_pct=size_pct,
            entry_price=entry_price,
            stop_price=stop_price,
            wave_label=wave_label,
            risk_pct=size_pct * risk_per_unit / entry_price,
        )

    def compute_exit_schedule(
        self,
        entry_price: float,
        first_target: float,
        second_target: float | None = None,
    ) -> list[PositionRequest]:
        """Compute staged exit schedule.

        Returns three exit requests:
        1. 30% at first target (e.g. 1.618 extension)
        2. 30% at second target or divergence
        3. 40% on wave invalidation
        """
        exits: list[PositionRequest] = []

        exits.append(
            PositionRequest(
                phase=PositionPhase.EXIT_FIRST,
                size_pct=self.config.exit_first_pct,
                entry_price=entry_price,
                stop_price=0,
                target_price=first_target,
            )
        )

        exits.append(
            PositionRequest(
                phase=PositionPhase.EXIT_SECOND,
                size_pct=self.config.exit_second_pct,
                entry_price=entry_price,
                stop_price=0,
                target_price=second_target,
            )
        )

        exits.append(
            PositionRequest(
                phase=PositionPhase.EXIT_FINAL,
                size_pct=self.config.exit_final_pct,
                entry_price=entry_price,
                stop_price=0,
            )
        )

        return exits

    def update_trailing_stop(
        self,
        current_price: float,
        wave_low: float,
        cost_basis: float,
    ) -> float:
        """Update trailing stop to cost basis or wave low, whichever is higher."""
        self._trailing_stop = max(cost_basis, wave_low)
        return self._trailing_stop

    def check_risk_limits(
        self,
        capital: float,
        daily_pnl: float,
        monthly_pnl: float,
    ) -> dict[str, bool]:
        """Check all risk limits.

        Returns dict of limit name → whether the limit is breached.
        """
        return {
            "daily_loss": daily_pnl < -capital * self.config.daily_loss_limit_pct,
            "monthly_loss": monthly_pnl < -capital * self.config.monthly_loss_limit_pct,
        }

    def size(self, capital: float, entry_price: float, stop_price: float) -> float:
        """Adapter method compatible with standard PositionSizer interface.

        Returns position size as a fraction of capital (0.0-1.0).
        Uses the trial position model as the default sizing method.
        """
        req = self.compute_trial_position(capital, entry_price, stop_price)
        return min(req.size_pct, self.config.trial_pct)
