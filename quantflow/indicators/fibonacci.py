"""Fibonacci retracement and extension calculator.

Computes Fibonacci levels based on wave structure, supporting both
retracement (0.236-0.786) and extension (1.0-2.618) ratios.
Directional computation: retracement levels for a down-wave are
calculated upward from wave end (SME-03).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import pandas as pd

from quantflow.indicators.base import FactorBase
from quantflow.indicators.wave_models import WaveCount, WavePattern


class FibLevelType(StrEnum):
    RETRACEMENT = "retracement"
    EXTENSION = "extension"


@dataclass
class FibonacciLevel:
    """A single Fibonacci price level with metadata."""

    ratio: float
    price: float
    level_type: FibLevelType
    label: str  # e.g. "0.618 retracement", "1.618 extension"


@dataclass
class FibonacciLevels:
    """Complete Fibonacci level set for a wave count."""

    retracement: dict[float, float] = field(default_factory=dict)
    extension: dict[float, float] = field(default_factory=dict)
    key_levels: list[FibonacciLevel] = field(default_factory=list)


# Standard Fibonacci ratios
RETRACEMENT_RATIOS = [0.236, 0.382, 0.5, 0.618, 0.786]
EXTENSION_RATIOS = [1.0, 1.236, 1.382, 1.618, 2.0, 2.618]


class FibonacciCalculator(FactorBase):
    """Fibonacci retracement and extension calculator.

    Computes levels based on the most recent completed wave in WaveCount.
    Directional computation: for a bullish impulse, retracement levels
    are calculated downward from W3 peak; extension levels upward from W1 base.
    For a bearish impulse, the direction is inverted (SME-03).
    """

    name = "fibonacci_levels"

    def compute(self, df: pd.DataFrame, **params: Any) -> pd.Series:
        """Compute Fibonacci levels and return the 0.618 retracement price."""
        wave_count = params.get("wave_count")
        if wave_count is None:
            return pd.Series(float("nan"), index=df.index)

        levels = self.calculate(wave_count)
        fib_618 = levels.retracement.get(0.618, float("nan"))
        return pd.Series(fib_618, index=df.index)

    def calculate(
        self,
        wave_count: WaveCount,
        retracement_ratios: list[float] | None = None,
        extension_ratios: list[float] | None = None,
    ) -> FibonacciLevels:
        """Calculate Fibonacci levels from a WaveCount.

        Args:
            wave_count: Current wave count from WaveIdentifier.
            retracement_ratios: Custom retracement ratios (default: standard).
            extension_ratios: Custom extension ratios (default: standard).

        Returns:
            FibonacciLevels with retracement, extension, and key levels.
        """
        ret_ratios = retracement_ratios or RETRACEMENT_RATIOS
        ext_ratios = extension_ratios or EXTENSION_RATIOS

        if wave_count.pattern == WavePattern.UNKNOWN:
            return FibonacciLevels()

        is_impulse = wave_count.pattern == WavePattern.IMPULSE

        if is_impulse:
            return self._calculate_impulse(wave_count, ret_ratios, ext_ratios)
        else:
            return self._calculate_corrective(wave_count, ret_ratios, ext_ratios)

    def _calculate_impulse(
        self,
        wave_count: WaveCount,
        ret_ratios: list[float],
        ext_ratios: list[float],
    ) -> FibonacciLevels:
        """Calculate Fibonacci levels for an impulse pattern.

        Retracement: from the high of the completed wave down to the start.
        Extension: from W1 start upward by extension ratios x W1 amplitude.
        """
        # Determine the reference wave for retracement
        # Typically use the most recent completed wave pair
        waves = wave_count.waves

        # For retracement, use the full move (start of W1 to end of last completed wave)
        if 1 not in waves:
            return FibonacciLevels()

        w1 = waves[1]
        is_bullish = w1.end.price > w1.start.price

        # Reference move for retracement calculation
        if is_bullish:
            # Find the highest point (likely W3 or W5)
            high_price = w1.end.price
            for i in [3, 5]:
                if i in waves:
                    high_price = max(high_price, waves[i].end.price)
            low_price = w1.start.price
        else:
            low_price = w1.end.price
            for i in [3, 5]:
                if i in waves:
                    low_price = min(low_price, waves[i].end.price)
            high_price = w1.start.price

        amplitude = high_price - low_price
        if amplitude <= 0:
            return FibonacciLevels()

        # Calculate retracement levels
        retracement: dict[float, float] = {}
        key_levels: list[FibonacciLevel] = []

        for ratio in ret_ratios:
            price = high_price - amplitude * ratio if is_bullish else low_price + amplitude * ratio

            retracement[ratio] = price
            label = f"{ratio:.3f} retracement ({price:.2f})"
            key_levels.append(
                FibonacciLevel(
                    ratio=ratio,
                    price=price,
                    level_type=FibLevelType.RETRACEMENT,
                    label=label,
                )
            )

        # Calculate extension levels (from W1 start)
        w1_amplitude = w1.amplitude()
        extension: dict[float, float] = {}

        for ratio in ext_ratios:
            if is_bullish:
                price = w1.start.price + w1_amplitude * ratio
            else:
                price = w1.start.price - w1_amplitude * ratio

            extension[ratio] = price
            label = f"{ratio:.3f} extension ({price:.2f})"
            key_levels.append(
                FibonacciLevel(
                    ratio=ratio,
                    price=price,
                    level_type=FibLevelType.EXTENSION,
                    label=label,
                )
            )

        return FibonacciLevels(
            retracement=retracement,
            extension=extension,
            key_levels=key_levels,
        )

    def _calculate_corrective(
        self,
        wave_count: WaveCount,
        ret_ratios: list[float],
        ext_ratios: list[float],
    ) -> FibonacciLevels:
        """Calculate Fibonacci levels for a corrective (A-B-C) pattern.

        Retracement of A wave, extension targets for C wave.
        """
        waves = wave_count.waves

        if -1 not in waves:
            return FibonacciLevels()

        wave_a = waves[-1]
        is_downward_a = wave_a.end.price < wave_a.start.price
        a_amplitude = wave_a.amplitude()

        if a_amplitude <= 0:
            return FibonacciLevels()

        # Retracement of A wave (B wave targets)
        retracement: dict[float, float] = {}
        key_levels: list[FibonacciLevel] = []

        for ratio in ret_ratios:
            if is_downward_a:
                price = wave_a.end.price + a_amplitude * ratio
            else:
                price = wave_a.end.price - a_amplitude * ratio

            retracement[ratio] = price
            label = f"{ratio:.3f} retracement of A ({price:.2f})"
            key_levels.append(
                FibonacciLevel(
                    ratio=ratio,
                    price=price,
                    level_type=FibLevelType.RETRACEMENT,
                    label=label,
                )
            )

        # Extension of A wave (C wave targets)
        extension: dict[float, float] = {}

        for ratio in ext_ratios:
            if is_downward_a:
                price = wave_a.start.price - a_amplitude * ratio
            else:
                price = wave_a.start.price + a_amplitude * ratio

            extension[ratio] = price
            label = f"{ratio:.3f} extension of A ({price:.2f})"
            key_levels.append(
                FibonacciLevel(
                    ratio=ratio,
                    price=price,
                    level_type=FibLevelType.EXTENSION,
                    label=label,
                )
            )

        return FibonacciLevels(
            retracement=retracement,
            extension=extension,
            key_levels=key_levels,
        )
