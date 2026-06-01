"""Elliott Wave identification engine.

Consumes PivotSequence from ZigZagIndicator and produces WaveCount with
iron-law validation. Supports dual analysis mode (RETROSPECTIVE/PROGRESSIVE)
per brainstorm resolution C-001.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quantflow.indicators.base import FactorBase
from quantflow.indicators.wave_models import (
    AnalysisMode,
    IronLawResult,
    PivotDirection,
    WaveCount,
    WavePattern,
    WaveSegment,
)
from quantflow.indicators.zigzag import PivotPoint, PivotSequence


class WaveIdentifier(FactorBase):
    """Elliott Wave pattern identifier with iron-law validation.

    Processes PivotSequence pivots and attempts to classify them into
    an Elliott Wave pattern (impulse 1-5 or corrective A-B-C).

    The identifier supports two modes:
    - RETROSPECTIVE: All three iron laws enforced strictly. Used after
      a wave pattern is complete for historical analysis.
    - PROGRESSIVE: Iron Law 2 (W3 not shortest) is checked but does not
      reject the classification. Used during live analysis where W3
      length is still uncertain. (C-001)
    """

    name = "wave_count"

    def compute(self, df: pd.DataFrame, **params: Any) -> pd.Series:
        """Compute wave count and return current wave label as a Series."""
        pivots_data = params.get("pivots")
        mode = params.get("mode", AnalysisMode.PROGRESSIVE)

        if pivots_data is None:
            return pd.Series(0, index=df.index, dtype=int)

        wave_count = self.identify(pivots_data, mode=mode)
        result = pd.Series(0, index=df.index, dtype=int)
        if wave_count.current_wave != 0:
            result.iloc[-1] = wave_count.current_wave
        return result

    def identify(
        self,
        pivots: PivotSequence,
        mode: AnalysisMode = AnalysisMode.PROGRESSIVE,
    ) -> WaveCount:
        """Identify wave pattern from a sequence of pivot points.

        Args:
            pivots: Consensus pivot sequence from ZigZagIndicator.
            mode: Analysis mode (RETROSPECTIVE or PROGRESSIVE).

        Returns:
            WaveCount with identified pattern and iron-law validation.
        """
        if len(pivots.pivots) < 5:
            return WaveCount(
                pattern=WavePattern.UNKNOWN,
                mode=mode,
                confidence=0.0,
            )

        # Try impulse pattern first
        impulse = self._try_impulse(pivots.pivots, mode)
        if impulse is not None:
            return impulse

        # Try corrective pattern
        corrective = self._try_corrective(pivots.pivots, mode)
        if corrective is not None:
            return corrective

        return WaveCount(
            pattern=WavePattern.UNKNOWN,
            mode=mode,
            confidence=0.0,
        )

    def _try_impulse(
        self,
        pivots: list[PivotPoint],
        mode: AnalysisMode,
    ) -> WaveCount | None:
        """Try to classify pivots as an impulse pattern (1-2-3-4-5)."""
        # Need at least 5 pivots for impulse: low-high-low-high-low
        # or high-low-high-low-high
        if len(pivots) < 5:
            return None

        # Check alternating direction pattern
        # Bullish impulse: LOW, HIGH, LOW, HIGH, LOW (or starting HIGH for bearish)
        bullish_start = pivots[0].direction == PivotDirection.LOW
        bearish_start = pivots[0].direction == PivotDirection.HIGH

        if not (bullish_start or bearish_start):
            return None

        # Build wave segments
        is_bullish = bullish_start
        waves: dict[int, WaveSegment] = {}

        for i in range(min(5, len(pivots) - 1)):
            wave_label = i + 1
            start_pivot = pivots[i]
            end_pivot = pivots[i + 1]

            # Direction consistency check
            expected_up = (is_bullish and wave_label % 2 == 1) or (not is_bullish and wave_label % 2 == 0)
            actual_up = end_pivot.price > start_pivot.price

            if expected_up != actual_up:
                break

            length_pct = (end_pivot.price - start_pivot.price) / start_pivot.price * 100

            # Compute retracement for waves 2, 4
            retracement_pct = None
            if wave_label in (2, 4) and wave_label - 1 in waves:
                prev = waves[wave_label - 1]
                if prev.amplitude() > 0:
                    retracement_pct = abs(end_pivot.price - start_pivot.price) / prev.amplitude() * 100

            waves[wave_label] = WaveSegment(
                label=wave_label,
                start=start_pivot,
                end=end_pivot,
                length_pct=length_pct,
                retracement_pct=retracement_pct,
            )

        if len(waves) < 3:
            return None

        # Validate iron laws
        iron_law = self._validate_iron_laws(waves, mode, is_bullish)

        # Determine current wave
        current_wave = len(waves)

        # Confidence based on number of identified waves and iron law status
        confidence = min(1.0, len(waves) / 5.0)
        if iron_law.has_warnings:
            confidence *= 0.8
        if not iron_law.is_valid:
            confidence *= 0.3

        return WaveCount(
            pattern=WavePattern.IMPULSE,
            current_wave=current_wave,
            waves=waves,
            mode=mode,
            confidence=confidence,
        )

    def _try_corrective(
        self,
        pivots: list[PivotPoint],
        mode: AnalysisMode,
    ) -> WaveCount | None:
        """Try to classify pivots as a corrective pattern (A-B-C)."""
        if len(pivots) < 3:
            return None

        # A-B-C: 3-wave pattern against the main trend
        # For bullish correction: HIGH, LOW, HIGH (retracing upward)
        # For bearish correction: LOW, HIGH, LOW (retracing downward)
        waves: dict[int, WaveSegment] = {}

        for i in range(min(3, len(pivots) - 1)):
            wave_label = -(i + 1)  # -1=A, -2=B, -3=C
            start_pivot = pivots[i]
            end_pivot = pivots[i + 1]

            length_pct = (end_pivot.price - start_pivot.price) / start_pivot.price * 100

            retracement_pct = None
            if wave_label == -2 and -1 in waves:
                prev = waves[-1]
                if prev.amplitude() > 0:
                    retracement_pct = abs(end_pivot.price - start_pivot.price) / prev.amplitude() * 100

            waves[wave_label] = WaveSegment(
                label=wave_label,
                start=start_pivot,
                end=end_pivot,
                length_pct=length_pct,
                retracement_pct=retracement_pct,
            )

        if len(waves) < 3:
            return None

        current_wave = len(waves)
        confidence = min(1.0, len(waves) / 3.0) * 0.7  # corrective less confident

        return WaveCount(
            pattern=WavePattern.CORRECTIVE,
            current_wave=current_wave,
            waves=waves,
            mode=mode,
            confidence=confidence,
        )

    def _validate_iron_laws(
        self,
        waves: dict[int, WaveSegment],
        mode: AnalysisMode,
        is_bullish: bool,
    ) -> IronLawResult:
        """Validate wave count against the three iron laws.

        Iron Law 1: W2 cannot retrace below W1 start (both modes).
        Iron Law 2: W3 cannot be the shortest of W1/W3/W5
            (RETROSPECTIVE: enforced; PROGRESSIVE: warning only per C-001).
        Iron Law 3: W4 cannot enter W1 price territory (both modes,
            diagonal triangle exception flagged).
        """
        result = IronLawResult(law2_mode=mode)
        warnings: list[str] = []
        violations: list[str] = []

        # Iron Law 1: W2 cannot go below W1 start
        if 1 in waves and 2 in waves:
            w1 = waves[1]
            w2 = waves[2]
            if is_bullish:
                if w2.end.price < w1.start.price:
                    result.law1_ok = False
                    violations.append(
                        f"Iron Law 1 violation: W2 low ({w2.end.price:.2f}) "
                        f"below W1 start ({w1.start.price:.2f})"
                    )
            else:
                if w2.end.price > w1.start.price:
                    result.law1_ok = False
                    violations.append(
                        f"Iron Law 1 violation: W2 high ({w2.end.price:.2f}) "
                        f"above W1 start ({w1.start.price:.2f})"
                    )

        # Iron Law 2: W3 cannot be the shortest of W1/W3/W5
        if 3 not in waves or 1 not in waves:
            result.law2_ok = None  # not yet determinable
        else:
            w1_amp = waves[1].amplitude()
            w3_amp = waves[3].amplitude()

            amplitudes = [w1_amp, w3_amp]
            if 5 in waves:
                w5_amp = waves[5].amplitude()
                if w5_amp > 0:
                    amplitudes.append(w5_amp)

            if len(amplitudes) >= 2 and w3_amp > 0:
                if w3_amp == min(amplitudes):
                    result.law2_ok = False
                    if mode == AnalysisMode.RETROSPECTIVE:
                        violations.append(
                            f"Iron Law 2 violation: W3 ({w3_amp:.2f}) is shortest of {amplitudes}"
                        )
                    else:
                        warnings.append(
                            f"Iron Law 2 warning: W3 ({w3_amp:.2f}) appears shortest "
                            f"(PROGRESSIVE mode, not rejecting classification)"
                        )
                else:
                    result.law2_ok = True
            else:
                result.law2_ok = None

        # Iron Law 3: W4 cannot enter W1 price territory
        if 1 in waves and 4 in waves:
            w1 = waves[1]
            w4 = waves[4]
            w1_low, w1_high = w1.price_range()

            if is_bullish:
                if w4.end.price < w1_high:
                    # Check for diagonal triangle exception
                    is_diagonal = self._check_diagonal(waves, is_bullish)
                    result.law3_ok = False
                    result.law3_diagonal = is_diagonal
                    if is_diagonal:
                        warnings.append(
                            f"Iron Law 3: W4 ({w4.end.price:.2f}) overlaps W1 ({w1_low:.2f}-{w1_high:.2f}), "
                            f"but diagonal triangle exception applies"
                        )
                    else:
                        violations.append(
                            f"Iron Law 3 violation: W4 ({w4.end.price:.2f}) "
                            f"enters W1 territory ({w1_low:.2f}-{w1_high:.2f})"
                        )
            else:
                if w4.end.price > w1_low:
                    is_diagonal = self._check_diagonal(waves, is_bullish)
                    result.law3_ok = False
                    result.law3_diagonal = is_diagonal
                    if is_diagonal:
                        warnings.append(
                            f"Iron Law 3: W4 ({w4.end.price:.2f}) overlaps W1, diagonal exception"
                        )
                    else:
                        violations.append(
                            f"Iron Law 3 violation: W4 ({w4.end.price:.2f}) enters W1 territory"
                        )

        result.warnings = warnings
        result.violations = violations
        return result

    def _check_diagonal(
        self,
        waves: dict[int, WaveSegment],
        is_bullish: bool,
    ) -> bool:
        """Check if the pattern is a diagonal (ending/leading diagonal).

        A diagonal has overlapping waves 1 and 4, and each sub-wave
        is a 3-wave structure. Simplified heuristic: check if W1 and W4
        overlap AND waves progressively narrow.
        """
        if len(waves) < 5:
            return False

        # Heuristic: check diminishing wave amplitudes
        amplitudes = [waves[i].amplitude() for i in range(1, 6) if i in waves]
        if len(amplitudes) >= 3:
            is_narrowing = all(amplitudes[i] <= amplitudes[i - 1] for i in range(1, len(amplitudes)))
            if is_narrowing:
                return True

        return False
