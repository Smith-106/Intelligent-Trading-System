"""Tests for Elliott Wave channel construction."""

from __future__ import annotations

import pandas as pd
import pytest

from quantflow.indicators.wave_channel import ChannelResult, WaveChannel
from quantflow.indicators.wave_models import WaveCount, WavePattern, WaveSegment
from quantflow.indicators.zigzag import PivotDirection, PivotPoint


def _pivot(index: int, price: float, direction: PivotDirection) -> PivotPoint:
    return PivotPoint(index=index, price=price, direction=direction, timestamp=index)


def _wave(label: int, start_idx: int, start_price: float, end_idx: int, end_price: float) -> WaveSegment:
    direction = PivotDirection.HIGH if end_price >= start_price else PivotDirection.LOW
    return WaveSegment(
        label=label,
        start=_pivot(start_idx, start_price, PivotDirection.LOW if direction == PivotDirection.HIGH else PivotDirection.HIGH),
        end=_pivot(end_idx, end_price, direction),
    )


def _frame(length: int = 12) -> pd.DataFrame:
    return pd.DataFrame({"close": range(length)}, index=pd.RangeIndex(length))


class TestWaveChannel:
    def test_compute_returns_nan_series_without_impulse_count(self) -> None:
        channel = WaveChannel()
        df = _frame(5)

        result_none = channel.compute(df)
        result_corrective = channel.compute(df, wave_count=WaveCount(pattern=WavePattern.CORRECTIVE))

        assert result_none.isna().all()
        assert result_corrective.isna().all()

    def test_compute_returns_target_when_channel_can_project_w5(self) -> None:
        channel = WaveChannel()
        df = _frame(10)
        wave_count = WaveCount(
            pattern=WavePattern.IMPULSE,
            waves={
                1: _wave(1, 0, 100.0, 2, 110.0),
                2: _wave(2, 2, 110.0, 3, 104.0),
                3: _wave(3, 3, 104.0, 5, 122.0),
                4: _wave(4, 5, 122.0, 6, 116.0),
            },
        )

        result = channel.compute(df, wave_count=wave_count)

        assert result.nunique() == 1
        assert result.iloc[0] == pytest.approx(134.0)

    def test_calculate_returns_empty_result_for_non_impulse_or_missing_waves(self) -> None:
        channel = WaveChannel()
        df = _frame()

        non_impulse = channel.calculate(df, WaveCount(pattern=WavePattern.CORRECTIVE))
        missing = channel.calculate(
            df,
            WaveCount(
                pattern=WavePattern.IMPULSE,
                waves={1: _wave(1, 0, 100.0, 1, 110.0), 2: _wave(2, 1, 110.0, 2, 105.0)},
            ),
        )

        assert non_impulse == ChannelResult()
        assert missing == ChannelResult()

    def test_calculate_returns_empty_when_reference_points_share_same_index(self) -> None:
        channel = WaveChannel()
        df = _frame()
        wave_count = WaveCount(
            pattern=WavePattern.IMPULSE,
            waves={
                1: _wave(1, 0, 100.0, 2, 110.0),
                2: _wave(2, 2, 110.0, 3, 104.0),
                3: _wave(3, 3, 104.0, 2, 118.0),
            },
        )

        result = channel.calculate(df, wave_count)

        assert result == ChannelResult()

    def test_calculate_builds_bullish_channel_and_in_range_target(self) -> None:
        channel = WaveChannel()
        df = _frame(10)
        wave_count = WaveCount(
            pattern=WavePattern.IMPULSE,
            waves={
                1: _wave(1, 0, 100.0, 2, 110.0),
                2: _wave(2, 2, 110.0, 3, 104.0),
                3: _wave(3, 3, 104.0, 5, 122.0),
                4: _wave(4, 5, 122.0, 6, 116.0),
            },
        )

        result = channel.calculate(df, wave_count)

        assert result.upper_band is not None
        assert result.lower_band is not None
        assert result.upper_band.iloc[2] == pytest.approx(110.0)
        assert result.upper_band.iloc[5] == pytest.approx(122.0)
        assert result.lower_band.iloc[3] == pytest.approx(104.0)
        assert result.w5_target == pytest.approx(134.0)

    def test_calculate_builds_bearish_channel_and_extrapolates_target(self) -> None:
        channel = WaveChannel()
        df = _frame(8)
        wave_count = WaveCount(
            pattern=WavePattern.IMPULSE,
            waves={
                1: _wave(1, 0, 120.0, 2, 110.0),
                2: _wave(2, 2, 110.0, 3, 116.0),
                3: _wave(3, 3, 116.0, 5, 100.0),
                4: _wave(4, 5, 100.0, 6, 106.0),
            },
        )

        result = channel.calculate(df, wave_count)

        assert result.upper_band is not None
        assert result.lower_band is not None
        assert result.lower_band.iloc[2] == pytest.approx(110.0)
        assert result.lower_band.iloc[5] == pytest.approx(100.0)
        assert result.upper_band.iloc[3] == pytest.approx(116.0)
        assert result.w5_target == pytest.approx(99.33333333333333)

    def test_calculate_without_wave4_leaves_target_unset(self) -> None:
        channel = WaveChannel()
        df = _frame(10)
        wave_count = WaveCount(
            pattern=WavePattern.IMPULSE,
            waves={
                1: _wave(1, 0, 100.0, 2, 110.0),
                2: _wave(2, 2, 110.0, 3, 104.0),
                3: _wave(3, 3, 104.0, 5, 122.0),
            },
        )

        result = channel.calculate(df, wave_count)

        assert result.upper_band is not None
        assert result.lower_band is not None
        assert result.w5_target is None
