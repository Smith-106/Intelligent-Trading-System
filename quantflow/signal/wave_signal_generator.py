"""Wave signal generator and invalidation checker.

WaveSignalGenerator bridges strategy signals with the standard Signal
model (CORR-016 fix), producing Signal objects consumable by RiskEngine
and PositionSizer.

WaveInvalidationChecker monitors critical levels and triggers
hard/soft stops when wave count is invalidated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging

from quantflow.common.models import Direction, Signal
from quantflow.indicators.critical_level import (
    BreachDirection,
    CriticalLevel,
    CriticalLevelType,
    CriticalLevels,
)
from quantflow.indicators.wave_models import WaveCount, WavePattern

logger = logging.getLogger(__name__)


class InvalidationSeverity(str, Enum):
    HARD = "hard"
    SOFT = "soft"


@dataclass
class InvalidationEvent:
    """An invalidation event triggered by a critical level breach."""
    severity: InvalidationSeverity
    critical_level: CriticalLevel
    current_price: float
    description: str


@dataclass
class WaveSignal(Signal):
    """A trading signal enriched with wave context and risk metadata.

    Extends the standard Signal model (CORR-016) so downstream
    RiskEngine and PositionSizer can consume it without adaptation.
    """
    wave_label: int = 0
    confidence: float = 0.0
    trigger_rule: str = ""
    invalidation_points: list[CriticalLevel] = field(default_factory=list)


class WaveSignalGenerator:
    """Generate wave-aware trading signals compatible with the Signal model.

    Produces WaveSignal (extends Signal) so RiskEngine/PositionSizer
    can consume it through the standard interface. Wave-specific
    metadata (wave_label, confidence, invalidation_points) is
    preserved as additional fields.
    """

    def enrich(
        self,
        direction: Direction,
        wave_count: WaveCount,
        critical_levels: CriticalLevels,
        trigger_rule: str = "",
        price: float = 0.0,
    ) -> WaveSignal:
        """Create a WaveSignal from wave analysis.

        Args:
            direction: Trade direction (LONG/SHORT).
            wave_count: Current wave count from WaveIdentifier.
            critical_levels: Critical levels from CriticalLevelDetector.
            trigger_rule: Name of the triggered rule (e.g. "w2_entry").
            price: Current price for stop calculation.

        Returns:
            WaveSignal with standard Signal fields + wave metadata.
        """
        hard_stop = self._compute_hard_stop(direction, critical_levels)
        soft_stop = self._compute_soft_stop(direction, critical_levels)

        invalidation_points = [
            cl for cl in critical_levels.levels if cl.severity == "hard"
        ]

        return WaveSignal(
            symbol="",
            direction=direction,
            price=price,
            wave_label=wave_count.current_wave,
            confidence=wave_count.confidence,
            trigger_rule=trigger_rule,
            invalidation_points=invalidation_points,
        )

    def _compute_hard_stop(
        self,
        direction: Direction,
        critical_levels: CriticalLevels,
    ) -> float | None:
        """Compute hard stop from critical levels."""
        hard_levels = [cl for cl in critical_levels.levels if cl.severity == "hard"]
        if not hard_levels:
            return None
        if direction == Direction.LONG:
            below = [cl.price for cl in hard_levels if cl.breach_direction == BreachDirection.BELOW]
            return min(below) if below else None
        else:
            above = [cl.price for cl in hard_levels if cl.breach_direction == BreachDirection.ABOVE]
            return max(above) if above else None

    def _compute_soft_stop(
        self,
        direction: Direction,
        critical_levels: CriticalLevels,
    ) -> float | None:
        """Compute soft stop from critical levels."""
        soft_levels = [cl for cl in critical_levels.levels if cl.severity == "soft"]
        if not soft_levels:
            return None
        if direction == Direction.LONG:
            below = [cl.price for cl in soft_levels if cl.breach_direction == BreachDirection.BELOW]
            return min(below) if below else None
        else:
            above = [cl.price for cl in soft_levels if cl.breach_direction == BreachDirection.ABOVE]
            return max(above) if above else None


class WaveInvalidationChecker:
    """Check wave invalidation conditions on every price update.

    Hard stops (must execute):
    - W1 origin breach → impulse invalid
    - W4 enters W1 territory → count invalid
    - Critical level breach with reverse direction → wave type change
    - Three consecutive stop losses → system pause

    Soft stops (dynamic adjustment):
    - Trailing stop: move up to cost or W2/W4 low after profit
    - Time stop: target not reached within expected time
    - Signal stop: MACD divergence disappears, volume anomaly
    """

    def __init__(self, max_consecutive_stops: int = 3):
        self.max_consecutive_stops = max_consecutive_stops
        self._consecutive_stops = 0

    def check(
        self,
        wave_count: WaveCount,
        critical_levels: CriticalLevels,
        current_price: float,
    ) -> list[InvalidationEvent]:
        """Check all invalidation conditions against current price.

        This method MUST execute synchronously in the bar handler (G-003)
        to guarantee atomic check-and-exit.
        """
        events: list[InvalidationEvent] = []

        for cl in critical_levels.levels:
            breached = False
            if cl.breach_direction == BreachDirection.BELOW and current_price < cl.price:
                breached = True
            elif cl.breach_direction == BreachDirection.ABOVE and current_price > cl.price:
                breached = True

            if breached:
                severity = InvalidationSeverity.HARD if cl.severity == "hard" else InvalidationSeverity.SOFT
                events.append(InvalidationEvent(
                    severity=severity,
                    critical_level=cl,
                    current_price=current_price,
                    description=f"{cl.level_type.value} breach: price {current_price:.2f} "
                                f"{'below' if cl.breach_direction == BreachDirection.BELOW else 'above'} "
                                f"critical {cl.price:.2f} ({cl.description})",
                ))

        hard_events = [e for e in events if e.severity == InvalidationSeverity.HARD]
        if hard_events:
            self._consecutive_stops += 1
        else:
            self._consecutive_stops = 0

        if self._consecutive_stops >= self.max_consecutive_stops:
            events.append(InvalidationEvent(
                severity=InvalidationSeverity.HARD,
                critical_level=CriticalLevel(
                    price=0,
                    level_type=CriticalLevelType.SYSTEM_PAUSE,
                    description="system_pause",
                    wave_ref=0,
                    severity="hard",
                ),
                current_price=current_price,
                description=f"System pause: {self._consecutive_stops} consecutive hard stops",
            ))

        return events

    def reset_consecutive(self) -> None:
        """Reset consecutive stop counter after a successful trade."""
        self._consecutive_stops = 0
