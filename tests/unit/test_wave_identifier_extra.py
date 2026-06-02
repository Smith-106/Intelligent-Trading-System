"""Additional branch coverage tests for the Elliott Wave identifier."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pandas as pd

from quantflow.indicators.wave_identifier import WaveIdentifier
from quantflow.indicators.wave_models import (
    AnalysisMode,
    IronLawResult,
    WaveCount,
    WavePattern,
    WaveSegment,
)
from quantflow.indicators.zigzag import PivotDirection, PivotPoint, PivotSequence


def _pivot(index: int, price: float, direction: PivotDirection) -> PivotPoint:
    return PivotPoint(index=index, price=price, direction=direction, timestamp=index)


def _sequence(points: list[tuple[int, float, PivotDirection]]) -> PivotSequence:
    return PivotSequence(pivots=[_pivot(idx, price, direction) for idx, price, direction in points])


def _wave(label: int, start_idx: int, start_price: float, end_idx: int, end_price: float) -> WaveSegment:
    direction = PivotDirection.HIGH if end_price >= start_price else PivotDirection.LOW
    return WaveSegment(
        label=label,
        start=_pivot(
            start_idx,
            start_price,
            PivotDirection.LOW if direction == PivotDirection.HIGH else PivotDirection.HIGH,
        ),
        end=_pivot(end_idx, end_price, direction),
    )


class TestWaveIdentifierExtra:
    def test_compute_returns_zero_series_without_pivots_and_marks_last_wave(self) -> None:
        identifier = WaveIdentifier()
        df = pd.DataFrame(index=pd.RangeIndex(4))

        empty = identifier.compute(df)

        with patch.object(
            identifier,
            "identify",
            return_value=WaveCount(pattern=WavePattern.IMPULSE, current_wave=4),
        ):
            marked = identifier.compute(df, pivots=_sequence([]))

        with patch.object(
            identifier,
            "identify",
            return_value=WaveCount(pattern=WavePattern.UNKNOWN, current_wave=0),
        ):
            unmarked = identifier.compute(df, pivots=_sequence([]))

        assert empty.eq(0).all()
        assert marked.iloc[-1] == 4
        assert unmarked.eq(0).all()

    def test_identify_returns_unknown_corrective_or_unknown_fallback(self) -> None:
        identifier = WaveIdentifier()
        short = _sequence(
            [
                (0, 100.0, PivotDirection.LOW),
                (1, 110.0, PivotDirection.HIGH),
                (2, 105.0, PivotDirection.LOW),
                (3, 115.0, PivotDirection.HIGH),
            ]
        )
        long_seq = _sequence(
            [
                (0, 100.0, PivotDirection.LOW),
                (1, 110.0, PivotDirection.HIGH),
                (2, 105.0, PivotDirection.LOW),
                (3, 115.0, PivotDirection.HIGH),
                (4, 108.0, PivotDirection.LOW),
            ]
        )
        corrective = WaveCount(pattern=WavePattern.CORRECTIVE, current_wave=3, confidence=0.7)

        short_result = identifier.identify(short, mode=AnalysisMode.RETROSPECTIVE)

        with (
            patch.object(identifier, "_try_impulse", return_value=None),
            patch.object(identifier, "_try_corrective", return_value=corrective),
        ):
            corrective_result = identifier.identify(long_seq)

        with (
            patch.object(identifier, "_try_impulse", return_value=None),
            patch.object(identifier, "_try_corrective", return_value=None),
        ):
            fallback_result = identifier.identify(long_seq)

        assert short_result.pattern == WavePattern.UNKNOWN
        assert short_result.mode == AnalysisMode.RETROSPECTIVE
        assert corrective_result is corrective
        assert fallback_result.pattern == WavePattern.UNKNOWN
        assert fallback_result.confidence == 0.0

    def test_try_impulse_handles_too_short_invalid_start_and_direction_break(self) -> None:
        identifier = WaveIdentifier()

        assert identifier._try_impulse([], AnalysisMode.PROGRESSIVE) is None

        invalid_start = [cast(PivotPoint, SimpleNamespace(direction=0, price=100.0, index=0))]
        assert identifier._try_impulse(invalid_start * 5, AnalysisMode.PROGRESSIVE) is None

        mismatch = [
            _pivot(0, 100.0, PivotDirection.LOW),
            _pivot(1, 110.0, PivotDirection.HIGH),
            _pivot(2, 105.0, PivotDirection.LOW),
            _pivot(3, 95.0, PivotDirection.LOW),
            _pivot(4, 108.0, PivotDirection.HIGH),
        ]
        assert identifier._try_impulse(mismatch, AnalysisMode.PROGRESSIVE) is None

    def test_try_impulse_scales_confidence_for_warning_and_invalid_results(self) -> None:
        identifier = WaveIdentifier()
        pivots = [
            _pivot(0, 100.0, PivotDirection.LOW),
            _pivot(1, 120.0, PivotDirection.HIGH),
            _pivot(2, 110.0, PivotDirection.LOW),
            _pivot(3, 150.0, PivotDirection.HIGH),
            _pivot(4, 130.0, PivotDirection.LOW),
            _pivot(5, 170.0, PivotDirection.HIGH),
        ]

        with patch.object(
            identifier,
            "_validate_iron_laws",
            return_value=IronLawResult(warnings=["law2 progressive warning"]),
        ):
            warning_result = identifier._try_impulse(pivots, AnalysisMode.PROGRESSIVE)

        with patch.object(
            identifier,
            "_validate_iron_laws",
            return_value=IronLawResult(law1_ok=False),
        ):
            invalid_result = identifier._try_impulse(pivots, AnalysisMode.PROGRESSIVE)

        assert warning_result is not None
        assert warning_result.pattern == WavePattern.IMPULSE
        assert warning_result.current_wave == 5
        assert warning_result.confidence == 0.8
        assert warning_result.waves[2].retracement_pct is not None
        assert warning_result.waves[4].retracement_pct is not None

        assert invalid_result is not None
        assert invalid_result.confidence == 0.3

    def test_try_corrective_handles_short_and_complete_sequences(self) -> None:
        identifier = WaveIdentifier()

        assert identifier._try_corrective([], AnalysisMode.PROGRESSIVE) is None

        two_wave = [
            _pivot(0, 120.0, PivotDirection.HIGH),
            _pivot(1, 100.0, PivotDirection.LOW),
            _pivot(2, 110.0, PivotDirection.HIGH),
        ]
        assert identifier._try_corrective(two_wave, AnalysisMode.PROGRESSIVE) is None

        pivots = [
            _pivot(0, 120.0, PivotDirection.HIGH),
            _pivot(1, 100.0, PivotDirection.LOW),
            _pivot(2, 110.0, PivotDirection.HIGH),
            _pivot(3, 90.0, PivotDirection.LOW),
        ]
        result = identifier._try_corrective(pivots, AnalysisMode.RETROSPECTIVE)

        assert result is not None
        assert result.pattern == WavePattern.CORRECTIVE
        assert result.current_wave == 3
        assert result.mode == AnalysisMode.RETROSPECTIVE
        assert result.confidence == 0.7
        assert result.waves[-2].retracement_pct == 50.0

    def test_validate_iron_laws_covers_bullish_and_bearish_branches(self) -> None:
        identifier = WaveIdentifier()

        indeterminate = identifier._validate_iron_laws({2: _wave(2, 0, 100.0, 1, 95.0)}, AnalysisMode.PROGRESSIVE, True)

        bullish_waves = {
            1: _wave(1, 0, 100.0, 1, 120.0),
            2: _wave(2, 1, 120.0, 2, 90.0),
            3: _wave(3, 2, 90.0, 3, 100.0),
            4: _wave(4, 3, 100.0, 4, 110.0),
            5: _wave(5, 4, 110.0, 5, 130.0),
        }
        progressive = identifier._validate_iron_laws(
            bullish_waves, AnalysisMode.PROGRESSIVE, True
        )
        retrospective = identifier._validate_iron_laws(
            bullish_waves, AnalysisMode.RETROSPECTIVE, True
        )

        diagonal_waves = {
            1: _wave(1, 0, 100.0, 1, 130.0),
            2: _wave(2, 1, 130.0, 2, 106.0),
            3: _wave(3, 2, 106.0, 3, 124.0),
            4: _wave(4, 3, 124.0, 4, 112.0),
            5: _wave(5, 4, 112.0, 5, 118.0),
        }
        diagonal = identifier._validate_iron_laws(diagonal_waves, AnalysisMode.PROGRESSIVE, True)

        bearish_waves = {
            1: _wave(1, 0, 120.0, 1, 100.0),
            2: _wave(2, 1, 100.0, 2, 125.0),
            3: _wave(3, 2, 125.0, 3, 90.0),
            4: _wave(4, 3, 90.0, 4, 115.0),
            5: _wave(5, 4, 115.0, 5, 80.0),
        }
        bearish = identifier._validate_iron_laws(bearish_waves, AnalysisMode.RETROSPECTIVE, False)

        assert indeterminate.law2_ok is None

        assert progressive.law1_ok is False
        assert progressive.law2_ok is False
        assert progressive.law3_ok is False
        assert progressive.law3_diagonal is False
        assert any("Iron Law 2 warning" in warning for warning in progressive.warnings)
        assert any("Iron Law 1 violation" in violation for violation in progressive.violations)
        assert any("Iron Law 3 violation" in violation for violation in progressive.violations)

        assert retrospective.law2_ok is False
        assert any("Iron Law 2 violation" in violation for violation in retrospective.violations)

        assert diagonal.law3_ok is False
        assert diagonal.law3_diagonal is True
        assert any("diagonal triangle exception applies" in warning for warning in diagonal.warnings)

        assert bearish.law1_ok is False
        assert bearish.law3_ok is False
        assert any("above W1 start" in violation for violation in bearish.violations)
        assert any("enters W1 territory" in violation for violation in bearish.violations)

    def test_check_diagonal_requires_enough_waves_and_narrowing_shape(self) -> None:
        identifier = WaveIdentifier()

        assert identifier._check_diagonal({1: _wave(1, 0, 100.0, 1, 120.0)}, True) is False

        narrowing = {
            1: _wave(1, 0, 100.0, 1, 130.0),
            2: _wave(2, 1, 130.0, 2, 106.0),
            3: _wave(3, 2, 106.0, 3, 124.0),
            4: _wave(4, 3, 124.0, 4, 112.0),
            5: _wave(5, 4, 112.0, 5, 118.0),
        }
        widening = {
            1: _wave(1, 0, 100.0, 1, 110.0),
            2: _wave(2, 1, 110.0, 2, 100.0),
            3: _wave(3, 2, 100.0, 3, 120.0),
            4: _wave(4, 3, 120.0, 4, 105.0),
            5: _wave(5, 4, 105.0, 5, 140.0),
        }

        assert identifier._check_diagonal(narrowing, True) is True
        assert identifier._check_diagonal(widening, True) is False

    def test_validate_iron_laws_sets_law2_to_none_when_wave3_amplitude_is_zero(self) -> None:
        identifier = WaveIdentifier()
        waves = {
            1: _wave(1, 0, 100.0, 1, 120.0),
            3: _wave(3, 2, 110.0, 2, 110.0),
        }

        result = identifier._validate_iron_laws(waves, AnalysisMode.PROGRESSIVE, True)

        assert result.law2_ok is None
