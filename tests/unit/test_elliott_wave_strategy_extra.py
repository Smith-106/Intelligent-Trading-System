"""Additional tests for the Liu Yudong Elliott Wave strategy."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pandas as pd

from quantflow.common.models import Bar
from quantflow.indicators.divergence import Divergence, DivergenceResult
from quantflow.indicators.fibonacci import FibonacciLevels
from quantflow.indicators.wave_channel import ChannelResult
from quantflow.indicators.wave_models import WaveCount, WavePattern, WaveSegment
from quantflow.indicators.zigzag import PivotDirection, PivotPoint, PivotSequence
from quantflow.strategy.base import StrategyContext
from quantflow.strategy.elliott_wave_strategy import LiuYudongWaveStrategy


def _pivot(index: int, price: float, direction: PivotDirection) -> PivotPoint:
    return PivotPoint(index=index, price=price, direction=direction, timestamp=index)


def _wave(
    label: int, start_idx: int, start_price: float, end_idx: int, end_price: float
) -> WaveSegment:
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


def _ohlcv_frame(length: int = 30, volume: float = 1000.0) -> pd.DataFrame:
    close = [100.0 + idx for idx in range(length)]
    return pd.DataFrame(
        {
            "open": close,
            "high": [price + 1.0 for price in close],
            "low": [price - 1.0 for price in close],
            "close": close,
            "volume": [volume] * length,
        },
        index=pd.RangeIndex(length),
    )


class TestLiuYudongWaveStrategyExtra:
    def test_on_init_and_on_bar_are_noops(self) -> None:
        strategy = LiuYudongWaveStrategy()
        ctx = StrategyContext()
        bar = Bar("BTC/USDT", 1, 100.0, 101.0, 99.0, 100.0, 1000.0)

        strategy.on_init(ctx)
        strategy.on_bar(ctx, bar)

    def test_generate_signals_returns_empty_series_for_short_input(self) -> None:
        strategy = LiuYudongWaveStrategy()

        entries, exits = strategy.generate_signals(_ohlcv_frame(10))

        assert entries.eq(False).all()
        assert exits.eq(False).all()

    def test_extract_pivots_converts_marker_series_into_sequence(self) -> None:
        strategy = LiuYudongWaveStrategy()
        pivot_series = pd.Series([0, 1, -1, 0], index=pd.RangeIndex(4), dtype=int)
        df = pd.DataFrame({"close": [100.0, 110.0, 105.0, 111.0]})

        result = strategy._extract_pivots(pivot_series, df)

        assert isinstance(result, PivotSequence)
        assert result.overlap_ratio == 1.0
        assert result.thresholds_used == strategy.zigzag_thresholds
        assert [(pivot.index, pivot.price, pivot.direction) for pivot in result.pivots] == [
            (1, 110.0, PivotDirection.HIGH),
            (2, 105.0, PivotDirection.LOW),
        ]

    def test_check_w2_entry_covers_missing_amplitude_retracement_volume_and_success(self) -> None:
        strategy = LiuYudongWaveStrategy()
        df = _ohlcv_frame(6)

        assert strategy._check_w2_entry(df, {}, True) is False

        zero_amp = {
            1: _wave(1, 0, 100.0, 0, 100.0),
            2: _wave(2, 0, 100.0, 1, 96.0),
        }
        assert strategy._check_w2_entry(df, zero_amp, True) is False

        bad_retracement = {
            1: _wave(1, 0, 100.0, 1, 110.0),
            2: _wave(2, 1, 110.0, 2, 108.5),
        }
        assert strategy._check_w2_entry(df, bad_retracement, True) is False

        high_w2_volume = _ohlcv_frame(6)
        high_w2_volume.loc[:, "volume"] = [1000.0, 1000.0, 900.0, 900.0, 1000.0, 1000.0]
        volume_rejected = {
            1: _wave(1, 0, 100.0, 1, 110.0),
            2: _wave(2, 1, 110.0, 3, 104.0),
        }
        assert strategy._check_w2_entry(high_w2_volume, volume_rejected, True) is False

        valid = {
            1: _wave(1, 0, 100.0, 1, 110.0),
            2: _wave(2, 1, 110.0, 2, 104.0),
        }
        assert strategy._check_w2_entry(df.drop(columns=["volume"]), valid, True) is True

    def test_check_w3_entry_covers_missing_amplitude_volume_and_success(self) -> None:
        strategy = LiuYudongWaveStrategy()

        assert strategy._check_w3_entry(_ohlcv_frame(10), {}, True) is False

        weak_w3 = {
            1: _wave(1, 0, 100.0, 1, 112.0),
            3: _wave(3, 2, 108.0, 4, 116.0),
        }
        assert strategy._check_w3_entry(_ohlcv_frame(10), weak_w3, True) is False

        low_volume_df = _ohlcv_frame(30)
        low_volume_df.loc[:, "volume"] = (
            [100.0] * 20 + [100.0, 100.0, 100.0, 100.0, 100.0] + [1000.0] * 5
        )
        low_volume = {
            1: _wave(1, 0, 100.0, 2, 110.0),
            3: _wave(3, 20, 108.0, 24, 123.0),
        }
        assert strategy._check_w3_entry(low_volume_df, low_volume, True) is False

        valid = {
            1: _wave(1, 0, 100.0, 1, 108.0),
            3: _wave(3, 5, 104.0, 10, 120.0),
        }
        assert strategy._check_w3_entry(_ohlcv_frame(15), valid, True) is True

    def test_check_w4_entry_covers_missing_amplitude_retracement_volume_and_success(self) -> None:
        strategy = LiuYudongWaveStrategy()
        df = _ohlcv_frame(8)

        assert strategy._check_w4_entry(df, {}, True) is False

        zero_amp = {
            3: _wave(3, 0, 100.0, 0, 100.0),
            4: _wave(4, 0, 100.0, 1, 96.0),
        }
        assert strategy._check_w4_entry(df, zero_amp, True) is False

        bad_retracement = {
            3: _wave(3, 0, 100.0, 3, 130.0),
            4: _wave(4, 3, 130.0, 4, 126.0),
        }
        assert strategy._check_w4_entry(df, bad_retracement, True) is False

        high_w4_volume = _ohlcv_frame(8)
        high_w4_volume.loc[:, "volume"] = [
            1000.0,
            1000.0,
            1000.0,
            1000.0,
            900.0,
            900.0,
            1000.0,
            1000.0,
        ]
        volume_rejected = {
            3: _wave(3, 0, 100.0, 3, 124.0),
            4: _wave(4, 3, 124.0, 5, 114.0),
        }
        assert strategy._check_w4_entry(high_w4_volume, volume_rejected, True) is False

        valid = {
            3: _wave(3, 0, 100.0, 3, 124.0),
            4: _wave(4, 3, 124.0, 4, 114.0),
        }
        assert strategy._check_w4_entry(df.drop(columns=["volume"]), valid, True) is True

    def test_check_w5_exit_requires_two_confirmations_across_branches(self) -> None:
        strategy = LiuYudongWaveStrategy()
        df = _ohlcv_frame(8)
        df.loc[:, "volume"] = [1000.0, 1000.0, 1200.0, 300.0, 600.0, 500.0, 500.0, 500.0]
        bullish_waves = {
            3: _wave(3, 0, 100.0, 2, 130.0),
            5: _wave(5, 2, 120.0, 3, 150.0),
        }
        divergence = DivergenceResult(
            divergences=[
                Divergence(
                    divergence_type="macd_bearish",
                    wave_ref=5,
                    strength=0.8,
                    price_at_div=150.0,
                    indicator_at_div=1.2,
                )
            ],
            bearish=True,
        )

        assert strategy._check_w5_exit(df, {}, True) is False
        assert strategy._check_w5_exit(df, bullish_waves, True, divergence=divergence) is True

        one_signal_only = strategy._check_w5_exit(
            df.drop(columns=["volume"]),
            bullish_waves,
            True,
            divergence=divergence,
            channel=ChannelResult(w5_target=170.0),
        )
        assert one_signal_only is False

        bearish_waves = {
            3: _wave(3, 0, 140.0, 2, 100.0),
            5: _wave(5, 2, 110.0, 3, 90.0),
        }
        fib_levels = FibonacciLevels(extension={1.618: 92.0})
        assert (
            strategy._check_w5_exit(
                df.drop(columns=["volume"]),
                bearish_waves,
                False,
                channel=ChannelResult(w5_target=91.0),
                fib_levels=fib_levels,
            )
            is True
        )

    def test_check_b_wave_exit_covers_missing_amplitude_retracement_volume_and_success(
        self,
    ) -> None:
        strategy = LiuYudongWaveStrategy()
        df = _ohlcv_frame(8)

        assert strategy._check_b_wave_exit(df, {}) is False

        zero_amp = {
            -1: _wave(-1, 0, 100.0, 0, 100.0),
            -2: _wave(-2, 0, 100.0, 1, 105.0),
        }
        assert strategy._check_b_wave_exit(df, zero_amp) is False

        bad_retracement = {
            -1: _wave(-1, 0, 110.0, 2, 100.0),
            -2: _wave(-2, 2, 100.0, 3, 108.0),
        }
        assert strategy._check_b_wave_exit(df, bad_retracement) is False

        high_b_volume = _ohlcv_frame(8)
        high_b_volume.loc[:, "volume"] = [
            1000.0,
            1000.0,
            700.0,
            900.0,
            1000.0,
            1000.0,
            1000.0,
            1000.0,
        ]
        volume_rejected = {
            -1: _wave(-1, 0, 110.0, 2, 100.0),
            -2: _wave(-2, 2, 100.0, 3, 105.0),
        }
        assert strategy._check_b_wave_exit(high_b_volume, volume_rejected) is False

        valid = {
            -1: _wave(-1, 0, 110.0, 2, 100.0),
            -2: _wave(-2, 2, 100.0, 3, 105.0),
        }
        assert strategy._check_b_wave_exit(df.drop(columns=["volume"]), valid) is True

    def test_indicator_helpers_return_series(self) -> None:
        close = pd.Series([100.0 + idx for idx in range(40)], dtype=float)

        macd_hist = LiuYudongWaveStrategy._compute_macd_histogram(close)
        rsi = LiuYudongWaveStrategy._compute_rsi(close)

        assert len(macd_hist) == len(close)
        assert len(rsi) == len(close)
        assert macd_hist.iloc[-1] > 0
        assert rsi.iloc[-1] >= 0
        assert rsi.iloc[-1] <= 100

    def test_generate_signals_handles_unknown_impulse_and_corrective_windows(self) -> None:
        strategy = LiuYudongWaveStrategy({"incremental_window": 200})
        df = _ohlcv_frame(130)

        impulse_waves = {
            1: _wave(1, 24, 100.0, 31, 115.0),
            2: _wave(2, 31, 115.0, 30, 106.0),
            3: _wave(3, 32, 107.0, 35, 135.0),
            4: _wave(4, 35, 135.0, 32, 124.0),
            5: _wave(5, 36, 130.0, 33, 150.0),
        }
        corrective_waves = {
            -1: _wave(-1, 72, 120.0, 76, 100.0),
            -2: _wave(-2, 76, 100.0, 80, 110.0),
        }

        wave_counts = [
            WaveCount(pattern=WavePattern.UNKNOWN),
            WaveCount(pattern=WavePattern.IMPULSE, waves=impulse_waves),
            WaveCount(pattern=WavePattern.CORRECTIVE, waves=corrective_waves),
        ]

        empty_signal = pd.Series(0, index=pd.RangeIndex(130), dtype=int)

        with (
            patch.object(
                strategy.zigzag, "compute", side_effect=[empty_signal, empty_signal, empty_signal]
            ),
            patch.object(strategy, "_extract_pivots", return_value=Mock()),
            patch.object(strategy.wave_identifier, "identify", side_effect=wave_counts),
            patch.object(
                strategy.fibonacci_calc,
                "calculate",
                return_value=FibonacciLevels(extension={1.618: 149.0}),
            ),
            patch.object(strategy.critical_level_det, "detect", return_value=Mock()),
            patch.object(
                strategy.wave_channel, "calculate", return_value=ChannelResult(w5_target=148.0)
            ),
            patch.object(
                strategy.divergence_det, "detect", return_value=DivergenceResult(bearish=True)
            ),
            patch.object(
                strategy,
                "_compute_macd_histogram",
                side_effect=lambda close: pd.Series(0.0, index=close.index),
            ),
            patch.object(
                strategy,
                "_compute_rsi",
                side_effect=lambda close: pd.Series(50.0, index=close.index),
            ),
            patch.object(strategy, "_check_w2_entry", return_value=True),
            patch.object(strategy, "_check_w3_entry", return_value=True),
            patch.object(strategy, "_check_w4_entry", return_value=True),
            patch.object(strategy, "_check_w5_exit", return_value=True),
            patch.object(strategy, "_check_b_wave_exit", return_value=True),
        ):
            entries, exits = strategy.generate_signals(df)

        assert bool(entries.iloc[30]) is True
        assert bool(entries.iloc[31]) is True
        assert bool(entries.iloc[32]) is True
        assert bool(exits.iloc[33]) is True
        assert bool(exits.iloc[80]) is True
