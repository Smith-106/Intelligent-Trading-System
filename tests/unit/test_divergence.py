"""Tests for wave-level divergence detection."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from quantflow.indicators.divergence import DivergenceDetector, DivergenceResult
from quantflow.indicators.wave_models import WaveCount, WavePattern, WaveSegment
from quantflow.indicators.zigzag import PivotDirection, PivotPoint


def _pivot(index: int, price: float, direction: PivotDirection) -> PivotPoint:
    return PivotPoint(index=index, price=price, direction=direction, timestamp=index)


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


def _frame(length: int = 8) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "macd_histogram": [0.0] * length,
            "volume": [1000.0] * length,
            "rsi_14": [40.0] * length,
        },
        index=pd.RangeIndex(length),
    )


class TestDivergenceDetector:
    def test_compute_returns_zero_series_without_wave_count(self) -> None:
        detector = DivergenceDetector()

        result = detector.compute(_frame(4))

        assert result.dtype == int
        assert result.eq(0).all()

    def test_compute_maps_detect_result_to_bearish_and_bullish_signal(self) -> None:
        detector = DivergenceDetector()
        df = _frame(5)
        wave_count = WaveCount(pattern=WavePattern.IMPULSE)

        with patch.object(detector, "detect", return_value=DivergenceResult(bearish=True)):
            bearish_signal = detector.compute(df, wave_count=wave_count)

        with patch.object(detector, "detect", return_value=DivergenceResult(bullish=True)):
            bullish_signal = detector.compute(df, wave_count=wave_count)

        assert bearish_signal.iloc[-1] == -1
        assert bullish_signal.iloc[-1] == 1

    def test_detect_returns_empty_result_for_non_impulse_counts(self) -> None:
        detector = DivergenceDetector()
        wave_count = WaveCount(pattern=WavePattern.CORRECTIVE)

        result = detector.detect(wave_count, _frame())

        assert result == DivergenceResult()

    def test_detect_collects_bearish_and_bullish_divergences(self) -> None:
        detector = DivergenceDetector()
        df = _frame()
        df.loc[:, "macd_histogram"] = [0.0, 1.0, 0.5, 5.0, 1.0, 2.0, 0.0, 0.0]
        df.loc[:, "volume"] = [100.0, 120.0, 110.0, 1000.0, 700.0, 600.0, 500.0, 400.0]
        df.loc[:, "rsi_14"] = [45.0, 20.0, 35.0, 55.0, 50.0, 48.0, 46.0, 44.0]

        wave_count = WaveCount(
            pattern=WavePattern.IMPULSE,
            current_wave=5,
            waves={
                1: _wave(1, 0, 100.0, 1, 110.0),
                2: _wave(2, 1, 110.0, 2, 90.0),
                3: _wave(3, 2, 90.0, 3, 130.0),
                5: _wave(5, 4, 120.0, 5, 145.0),
            },
        )

        result = detector.detect(wave_count, df)

        assert result.bearish is True
        assert result.bullish is True
        assert [div.divergence_type for div in result.divergences] == [
            "macd_bearish",
            "volume_bearish",
            "rsi_bullish",
        ]

    def test_detect_marks_bullish_when_macd_bullish_divergence_is_found(self) -> None:
        detector = DivergenceDetector()
        df = _frame(6)
        df.loc[:, "macd_histogram"] = [0.0, -1.0, -5.0, -2.0, 0.0, 0.0]

        wave_count = WaveCount(
            pattern=WavePattern.IMPULSE,
            current_wave=5,
            waves={
                3: _wave(3, 0, 140.0, 2, 100.0),
                5: _wave(5, 3, 110.0, 3, 90.0),
            },
        )

        result = detector.detect(wave_count, df[["macd_histogram"]])

        assert result.bullish is True
        assert result.bearish is False
        assert [div.divergence_type for div in result.divergences] == ["macd_bullish"]

    def test_check_macd_divergence_handles_missing_and_out_of_range_waves(self) -> None:
        detector = DivergenceDetector()
        bullish_w3 = _wave(3, 1, 100.0, 2, 130.0)
        bullish_w5 = _wave(5, 3, 120.0, 8, 145.0)

        assert detector._check_macd_divergence({3: bullish_w3}, _frame()) is None
        assert detector._check_macd_divergence({3: bullish_w3, 5: bullish_w5}, _frame(5)) is None

    def test_check_macd_divergence_detects_bearish_and_bullish_setups(self) -> None:
        detector = DivergenceDetector()

        bullish_df = _frame(6)
        bullish_df.loc[:, "macd_histogram"] = [0.0, 1.0, 4.0, 2.0, 0.0, 0.0]
        bearish_result = detector._check_macd_divergence(
            {
                3: _wave(3, 0, 100.0, 2, 130.0),
                5: _wave(5, 3, 120.0, 3, 145.0),
            },
            bullish_df,
        )

        bearish_df = _frame(6)
        bearish_df.loc[:, "macd_histogram"] = [0.0, -1.0, -5.0, -2.0, 0.0, 0.0]
        bullish_result = detector._check_macd_divergence(
            {
                3: _wave(3, 0, 140.0, 2, 100.0),
                5: _wave(5, 3, 110.0, 3, 90.0),
            },
            bearish_df,
        )

        no_divergence = detector._check_macd_divergence(
            {
                3: _wave(3, 0, 100.0, 2, 130.0),
                5: _wave(5, 3, 120.0, 3, 145.0),
            },
            _frame(6),
        )

        assert bearish_result is not None
        assert bearish_result.divergence_type == "macd_bearish"
        assert bullish_result is not None
        assert bullish_result.divergence_type == "macd_bullish"
        assert no_divergence is None

    def test_check_volume_divergence_detects_bearish_and_bullish_setups(self) -> None:
        detector = DivergenceDetector()

        bullish_df = _frame(6)
        bullish_df.loc[:, "volume"] = [100.0, 200.0, 1000.0, 600.0, 0.0, 0.0]
        bearish_result = detector._check_volume_divergence(
            {
                3: _wave(3, 0, 100.0, 2, 130.0),
                5: _wave(5, 3, 120.0, 3, 145.0),
            },
            bullish_df,
        )

        bearish_df = _frame(6)
        bearish_df.loc[:, "volume"] = [100.0, 200.0, 900.0, 500.0, 0.0, 0.0]
        bullish_result = detector._check_volume_divergence(
            {
                3: _wave(3, 0, 140.0, 2, 100.0),
                5: _wave(5, 3, 110.0, 3, 90.0),
            },
            bearish_df,
        )

        out_of_range = detector._check_volume_divergence(
            {
                3: _wave(3, 0, 100.0, 9, 130.0),
                5: _wave(5, 3, 120.0, 10, 145.0),
            },
            _frame(6),
        )

        no_divergence = detector._check_volume_divergence(
            {
                3: _wave(3, 0, 100.0, 2, 130.0),
                5: _wave(5, 3, 120.0, 3, 145.0),
            },
            _frame(6),
        )

        assert bearish_result is not None
        assert bearish_result.divergence_type == "volume_bearish"
        assert bullish_result is not None
        assert bullish_result.divergence_type == "volume_bullish"
        assert out_of_range is None
        assert no_divergence is None

    def test_check_volume_divergence_returns_none_when_wave5_is_missing(self) -> None:
        detector = DivergenceDetector()

        assert detector._check_volume_divergence({3: _wave(3, 0, 100.0, 2, 130.0)}, _frame()) is None

    def test_check_rsi_divergence_handles_missing_out_of_range_and_bullish_cases(self) -> None:
        detector = DivergenceDetector()

        assert detector._check_rsi_divergence({2: _wave(2, 1, 110.0, 2, 90.0)}, _frame()) is None

        out_of_range = detector._check_rsi_divergence(
            {
                1: _wave(1, 0, 100.0, 9, 110.0),
                2: _wave(2, 9, 110.0, 10, 90.0),
            },
            _frame(6),
        )

        bullish_df = _frame(6)
        bullish_df.loc[:, "rsi_14"] = [45.0, 20.0, 35.0, 40.0, 42.0, 44.0]
        bullish_result = detector._check_rsi_divergence(
            {
                1: _wave(1, 0, 100.0, 1, 110.0),
                2: _wave(2, 1, 110.0, 2, 90.0),
            },
            bullish_df,
        )

        bearish_w1 = _wave(1, 0, 110.0, 1, 100.0)
        no_divergence = detector._check_rsi_divergence(
            {
                1: bearish_w1,
                2: _wave(2, 1, 100.0, 2, 95.0),
            },
            bullish_df,
        )

        assert out_of_range is None
        assert bullish_result is not None
        assert bullish_result.divergence_type == "rsi_bullish"
        assert no_divergence is None
