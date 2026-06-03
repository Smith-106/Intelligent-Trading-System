"""Additional coverage for legacy Elliott Wave helpers."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from quantflow.indicators.elliott_wave import (
    WaveLabel,
    WaveType,
    classify_corrective,
    classify_impulse,
    elliott_wave,
    wave_momentum_divergence,
    zigzag,
)


class TestZigZagExtra:
    def test_rejects_non_positive_threshold(self) -> None:
        high = pd.Series([100.0, 101.0, 102.0])
        low = pd.Series([99.0, 100.0, 101.0])

        with pytest.raises(ValueError, match="threshold must be positive"):
            zigzag(high, low, threshold=0.0)

    def test_detects_initial_down_move_and_appends_final_high_pivot(self) -> None:
        high = pd.Series([100.0, 96.0, 95.0, 100.0, 106.0], dtype=float)
        low = pd.Series([100.0, 94.0, 90.0, 95.0, 100.0], dtype=float)

        result = zigzag(high, low, threshold=0.05)

        assert len(result) == 3
        assert result.iloc[0].to_dict() == {
            "pivot_idx": 0,
            "pivot_price": 100.0,
            "pivot_type": 1,
        }
        assert result.iloc[1]["pivot_idx"] == 2
        assert result.iloc[1]["pivot_type"] == -1
        assert result.iloc[2]["pivot_idx"] == 4
        assert result.iloc[2]["pivot_type"] == 1


class TestClassifyImpulseExtra:
    def test_rejects_non_alternating_bearish_ratio_and_overlap_cases(self) -> None:
        non_alternating = pd.DataFrame(
            {
                "pivot_idx": [0, 1, 2, 3, 4],
                "pivot_price": [100.0, 120.0, 110.0, 130.0, 125.0],
                "pivot_type": [-1, 1, 1, -1, 1],
            }
        )
        bearish_invalid_w3 = pd.DataFrame(
            {
                "pivot_idx": [0, 1, 2, 3, 4],
                "pivot_price": [130.0, 100.0, 118.0, 121.0, 105.0],
                "pivot_type": [1, -1, 1, -1, 1],
            }
        )
        bearish_bad_r2 = pd.DataFrame(
            {
                "pivot_idx": [0, 1, 2, 3, 4],
                "pivot_price": [130.0, 100.0, 104.0, 70.0, 105.0],
                "pivot_type": [1, -1, 1, -1, 1],
            }
        )
        bearish_bad_r3 = pd.DataFrame(
            {
                "pivot_idx": [0, 1, 2, 3, 4],
                "pivot_price": [130.0, 100.0, 118.0, 110.0, 105.0],
                "pivot_type": [1, -1, 1, -1, 1],
            }
        )
        bearish_overlap = pd.DataFrame(
            {
                "pivot_idx": [0, 1, 2, 3, 4],
                "pivot_price": [130.0, 100.0, 118.0, 70.0, 95.0],
                "pivot_type": [1, -1, 1, -1, 1],
            }
        )

        assert classify_impulse(non_alternating) is None
        assert classify_impulse(bearish_invalid_w3) is None
        assert classify_impulse(bearish_bad_r2) is None
        assert classify_impulse(bearish_bad_r3) is None
        assert classify_impulse(bearish_overlap) is None

    def test_classifies_valid_bearish_impulse(self) -> None:
        pivots = pd.DataFrame(
            {
                "pivot_idx": [0, 1, 2, 3, 4],
                "pivot_price": [130.0, 100.0, 118.0, 70.0, 125.0],
                "pivot_type": [1, -1, 1, -1, 1],
            }
        )

        result = classify_impulse(pivots)

        assert result is not None
        assert result["wave_type"].eq(WaveType.IMPULSE).all()
        assert result["is_bullish"].eq(False).all()
        assert result["wave_label"].tolist() == [
            WaveLabel.W1,
            WaveLabel.W2,
            WaveLabel.W3,
            WaveLabel.W4,
            WaveLabel.W5,
        ]


class TestClassifyCorrectiveExtra:
    def test_rejects_too_short_non_alternating_zero_a_invalid_b_and_invalid_c(self) -> None:
        too_short = pd.DataFrame(
            {"pivot_idx": [0, 1], "pivot_price": [100.0, 110.0], "pivot_type": [-1, 1]}
        )
        non_alternating = pd.DataFrame(
            {
                "pivot_idx": [0, 1, 2],
                "pivot_price": [100.0, 110.0, 105.0],
                "pivot_type": [-1, 1, 1],
            }
        )
        zero_a = pd.DataFrame(
            {
                "pivot_idx": [0, 1, 2],
                "pivot_price": [100.0, 100.0, 105.0],
                "pivot_type": [-1, 1, -1],
            }
        )
        bad_b = pd.DataFrame(
            {
                "pivot_idx": [0, 1, 2],
                "pivot_price": [100.0, 120.0, 90.0],
                "pivot_type": [-1, 1, -1],
            }
        )
        bad_c = pd.DataFrame(
            {
                "pivot_idx": [0, 1, 2],
                "pivot_price": [100.0, 120.0, 108.0],
                "pivot_type": [-1, 1, -1],
            }
        )

        assert classify_corrective(too_short) is None
        assert classify_corrective(non_alternating) is None
        assert classify_corrective(zero_a) is None
        assert classify_corrective(bad_b) is None
        assert classify_corrective(bad_c) is None


class TestElliottWaveExtra:
    def test_falls_back_to_corrective_and_maps_rows_back_to_index(self) -> None:
        df = pd.DataFrame(
            {
                "high": [110.0, 120.0, 115.0, 125.0],
                "low": [100.0, 105.0, 102.0, 108.0],
            },
            index=pd.Index([10, 11, 12, 13]),
        )
        pivots = pd.DataFrame(
            {
                "pivot_idx": [0, 2, 3],
                "pivot_price": [100.0, 115.0, 108.0],
                "pivot_type": [-1, 1, -1],
            }
        )
        wave_df = pd.DataFrame(
            {
                "pivot_idx": [0, 2, 3],
                "pivot_price": [100.0, 115.0, 108.0],
                "pivot_type": [-1, 1, -1],
                "wave_label": [WaveLabel.WA, WaveLabel.WB, WaveLabel.WC],
                "wave_type": [WaveType.CORRECTIVE] * 3,
                "is_bullish": [True, True, True],
            }
        )

        with (
            patch("quantflow.indicators.elliott_wave.zigzag", return_value=pivots),
            patch("quantflow.indicators.elliott_wave.classify_impulse", return_value=None),
            patch("quantflow.indicators.elliott_wave.classify_corrective", return_value=wave_df),
        ):
            result = elliott_wave(df, zigzag_threshold=0.03, fib_tolerance=0.1)

        assert result.loc[10, "wave_label"] == int(WaveLabel.WA)
        assert result.loc[12, "wave_label"] == int(WaveLabel.WB)
        assert result.loc[13, "wave_label"] == int(WaveLabel.WC)
        assert result.loc[10, "wave_type"] == int(WaveType.CORRECTIVE)
        assert bool(result.loc[10, "is_bullish"]) is True
        assert result.loc[13, "pivot_price"] == 108.0


class TestWaveMomentumDivergenceExtra:
    def test_handles_short_pivots_out_of_range_and_detects_bullish_bearish(self) -> None:
        close = pd.Series([100.0, 98.0, 96.0, 95.0, 110.0, 112.0, 115.0], dtype=float)
        rsi = pd.Series([40.0, 35.0, 42.0, 45.0, 30.0, 58.0, 50.0], dtype=float)
        short_pivots = pd.DataFrame(
            {"pivot_idx": [0, 1, 2], "pivot_price": [100.0, 98.0, 95.0], "pivot_type": [-1, 1, -1]}
        )
        rich_pivots = pd.DataFrame(
            {
                "pivot_idx": [1, 2, 3, 4, 6, 8],
                "pivot_price": [98.0, 102.0, 95.0, 110.0, 115.0, 120.0],
                "pivot_type": [-1, 1, -1, 1, 1, -1],
            }
        )

        short_result = wave_momentum_divergence(close, rsi, short_pivots)
        rich_result = wave_momentum_divergence(close, rsi, rich_pivots, lookback=1)

        assert short_result.eq(0).all()
        assert rich_result.iloc[3] == 1
        assert rich_result.iloc[4] == -1

    def test_skips_pivots_that_do_not_have_enough_lookback(self) -> None:
        close = pd.Series([100.0, 99.0, 98.0, 97.0, 96.0], dtype=float)
        rsi = pd.Series([40.0, 41.0, 42.0, 43.0, 44.0], dtype=float)
        pivots = pd.DataFrame(
            {
                "pivot_idx": [0, 1, 2, 3],
                "pivot_price": [100.0, 101.0, 99.0, 102.0],
                "pivot_type": [-1, 1, -1, 1],
            }
        )

        result = wave_momentum_divergence(close, rsi, pivots, lookback=3)

        assert result.eq(0).all()
