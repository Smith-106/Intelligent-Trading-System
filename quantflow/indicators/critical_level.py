"""Critical level detector for Elliott Wave invalidation.

Identifies multi-space critical levels (多空临界位) — price levels where
a breach changes the wave classification. Supports dual scenario
(bull/bear) annotation per Liu Yudong's analytical style.

Critical levels are recomputed when WaveCount state changes (G-002).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd

from quantflow.indicators.base import FactorBase
from quantflow.indicators.wave_models import WaveCount, WavePattern


class CriticalLevelType(str, Enum):
    W1_ORIGIN = "w1_origin"
    W1_PEAK = "w1_peak"
    W3_PEAK = "w3_peak"
    W4_LOW = "w4_low"
    FIB_TARGET = "fib_target"
    SYSTEM_PAUSE = "system_pause"


class BreachDirection(str, Enum):
    ABOVE = "above"  # Price going above this level is significant
    BELOW = "below"  # Price going below this level is significant


@dataclass
class CriticalLevel:
    """A single critical price level with breach semantics."""
    price: float
    level_type: CriticalLevelType
    description: str
    wave_ref: int  # which wave this level pertains to
    breach_direction: BreachDirection = BreachDirection.BELOW
    severity: str = "hard"  # "hard" or "soft"


@dataclass
class Scenario:
    """A bull or bear scenario with trigger level and targets."""
    direction: str  # "bull" or "bear"
    trigger_level: CriticalLevel | None = None
    targets: list[float] = field(default_factory=list)


@dataclass
class CriticalLevels:
    """Complete set of critical levels for a wave count."""
    levels: list[CriticalLevel] = field(default_factory=list)
    active_bull_scenario: Scenario | None = None
    active_bear_scenario: Scenario | None = None


class CriticalLevelDetector(FactorBase):
    """Detect critical price levels from wave count.

    Critical levels are price points where a breach changes the wave
    classification. Per Liu Yudong's style, these are annotated with
    precise prices and dual bull/bear scenarios.

    Example (Liu Yudong April 2025 analysis):
    - Bull scenario: Break 91233 → W3 confirmed, target 96188 (1.618 ext)
    - Bear scenario: Break below 79038 → still in down wave
    """

    name = "critical_levels"

    def compute(self, df: pd.DataFrame, **params: Any) -> pd.Series:
        """Compute critical levels and return the nearest hard level price."""
        wave_count = params.get("wave_count")
        if wave_count is None:
            return pd.Series(float("nan"), index=df.index)

        levels = self.detect(wave_count)
        hard_levels = [l.price for l in levels.levels if l.severity == "hard"]
        if not hard_levels:
            return pd.Series(float("nan"), index=df.index)

        current_price = df["close"].iloc[-1] if "close" in df.columns else 0
        nearest = min(hard_levels, key=lambda p: abs(p - current_price))
        return pd.Series(nearest, index=df.index)

    def detect(self, wave_count: WaveCount) -> CriticalLevels:
        """Detect critical levels from current wave count.

        Critical levels are recomputed when WaveCount state changes (G-002).
        """
        if wave_count.pattern == WavePattern.UNKNOWN:
            return CriticalLevels()

        waves = wave_count.waves
        levels: list[CriticalLevel] = []

        is_impulse = wave_count.pattern == WavePattern.IMPULSE

        if is_impulse:
            levels = self._impulse_critical_levels(waves)
        else:
            levels = self._corrective_critical_levels(waves)

        # Build scenarios
        bull_scenario = self._build_bull_scenario(wave_count, levels)
        bear_scenario = self._build_bear_scenario(wave_count, levels)

        return CriticalLevels(
            levels=levels,
            active_bull_scenario=bull_scenario,
            active_bear_scenario=bear_scenario,
        )

    def _impulse_critical_levels(
        self,
        waves: dict,
    ) -> list[CriticalLevel]:
        """Extract critical levels from an impulse wave count."""
        levels: list[CriticalLevel] = []

        if 1 in waves:
            w1 = waves[1]
            is_bullish = w1.end.price > w1.start.price

            # W1 origin: breach invalidates the impulse
            levels.append(CriticalLevel(
                price=w1.start.price,
                level_type=CriticalLevelType.W1_ORIGIN,
                description=f"W1 origin ({w1.start.price:.2f}): breach invalidates impulse",
                wave_ref=1,
                breach_direction=BreachDirection.BELOW if is_bullish else BreachDirection.ABOVE,
                severity="hard",
            ))

            # W1 peak: breach confirms W3
            levels.append(CriticalLevel(
                price=w1.end.price,
                level_type=CriticalLevelType.W1_PEAK,
                description=f"W1 peak ({w1.end.price:.2f}): breach confirms W3",
                wave_ref=1,
                breach_direction=BreachDirection.ABOVE if is_bullish else BreachDirection.BELOW,
                severity="hard",
            ))

        if 3 in waves:
            w3 = waves[3]
            is_bullish = w3.end.price > w3.start.price

            # W3 peak: breach advances W5
            levels.append(CriticalLevel(
                price=w3.end.price,
                level_type=CriticalLevelType.W3_PEAK,
                description=f"W3 peak ({w3.end.price:.2f}): breach advances W5",
                wave_ref=3,
                breach_direction=BreachDirection.ABOVE if is_bullish else BreachDirection.BELOW,
                severity="soft",
            ))

        if 4 in waves:
            w4 = waves[4]
            is_bullish = w4.end.price > w4.start.price

            # W4 low: breach invalidates wave count
            levels.append(CriticalLevel(
                price=w4.end.price,
                level_type=CriticalLevelType.W4_LOW,
                description=f"W4 low ({w4.end.price:.2f}): breach invalidates count",
                wave_ref=4,
                breach_direction=BreachDirection.BELOW if is_bullish else BreachDirection.ABOVE,
                severity="hard",
            ))

        return levels

    def _corrective_critical_levels(
        self,
        waves: dict,
    ) -> list[CriticalLevel]:
        """Extract critical levels from a corrective wave count."""
        levels: list[CriticalLevel] = []

        if -1 in waves:
            wa = waves[-1]
            levels.append(CriticalLevel(
                price=wa.end.price,
                level_type=CriticalLevelType.W1_ORIGIN,
                description=f"A-wave end ({wa.end.price:.2f}): breach changes correction type",
                wave_ref=-1,
                severity="hard",
            ))

        if -2 in waves:
            wb = waves[-2]
            levels.append(CriticalLevel(
                price=wb.end.price,
                level_type=CriticalLevelType.W1_PEAK,
                description=f"B-wave peak ({wb.end.price:.2f}): breach above = irregular correction",
                wave_ref=-2,
                severity="soft",
            ))

        return levels

    def _build_bull_scenario(
        self,
        wave_count: WaveCount,
        levels: list[CriticalLevel],
    ) -> Scenario:
        """Build bull scenario with trigger and targets."""
        trigger = None
        targets: list[float] = []

        # Bull trigger: W1 peak breakout
        for l in levels:
            if l.level_type == CriticalLevelType.W1_PEAK:
                trigger = l
                break

        # Bull targets: Fibonacci extensions from wave count
        if 1 in wave_count.waves:
            w1 = wave_count.waves[1]
            w1_amp = w1.amplitude()
            if w1_amp > 0:
                targets = [
                    w1.start.price + w1_amp * 1.618,
                    w1.start.price + w1_amp * 2.618,
                ]

        return Scenario(direction="bull", trigger_level=trigger, targets=targets)

    def _build_bear_scenario(
        self,
        wave_count: WaveCount,
        levels: list[CriticalLevel],
    ) -> Scenario:
        """Build bear scenario with trigger and targets."""
        trigger = None
        targets: list[float] = []

        # Bear trigger: W1 origin breach
        for l in levels:
            if l.level_type == CriticalLevelType.W1_ORIGIN:
                trigger = l
                break

        # Bear targets: if W1 origin breached, look for support levels
        if 1 in wave_count.waves:
            w1 = wave_count.waves[1]
            w1_amp = w1.amplitude()
            if w1_amp > 0:
                targets = [
                    w1.start.price - w1_amp * 0.618,
                    w1.start.price - w1_amp * 1.0,
                ]

        return Scenario(direction="bear", trigger_level=trigger, targets=targets)
