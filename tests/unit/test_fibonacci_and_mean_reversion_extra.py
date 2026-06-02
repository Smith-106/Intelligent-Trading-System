"""Extra coverage for Fibonacci calculator and mean reversion strategy."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from quantflow.common.models import Bar, Direction, Signal
from quantflow.indicators.fibonacci import FibonacciCalculator, FibonacciLevels
from quantflow.indicators.wave_models import WaveCount, WavePattern, WaveSegment
from quantflow.indicators.zigzag import PivotDirection, PivotPoint
from quantflow.strategy.base import StrategyContext
from quantflow.strategy.templates.mean_reversion import MeanReversionStrategy


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


def _bar(idx: int, close: float, symbol: str = "BTC/USDT", volume: float = 1000.0) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=1_700_000_000_000 + idx * 60_000,
        open=close - 0.5,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=volume,
    )


class TestFibonacciCalculatorExtra:
    def test_compute_returns_nan_without_wave_count(self) -> None:
        calc = FibonacciCalculator()
        df = pd.DataFrame(index=pd.RangeIndex(3))

        result = calc.compute(df)

        assert result.isna().all()

    def test_compute_returns_nan_when_0618_retracement_is_missing(self) -> None:
        calc = FibonacciCalculator()
        df = pd.DataFrame(index=pd.RangeIndex(2))
        wave_count = WaveCount(pattern=WavePattern.UNKNOWN)

        with patch.object(calc, "calculate", return_value=FibonacciLevels(retracement={0.5: 100.0})):
            result = calc.compute(df, wave_count=wave_count)

        assert result.isna().all()

    def test_calculate_handles_unknown_missing_w1_and_zero_amplitude_impulse(self) -> None:
        calc = FibonacciCalculator()

        unknown = calc.calculate(WaveCount(pattern=WavePattern.UNKNOWN))
        missing_w1 = calc.calculate(WaveCount(pattern=WavePattern.IMPULSE, waves={3: _wave(3, 1, 110.0, 2, 120.0)}))
        zero_amp = calc.calculate(
            WaveCount(
                pattern=WavePattern.IMPULSE,
                waves={1: _wave(1, 0, 100.0, 0, 100.0)},
            )
        )

        assert unknown == FibonacciLevels()
        assert missing_w1 == FibonacciLevels()
        assert zero_amp == FibonacciLevels()

    def test_calculate_impulse_for_bullish_and_bearish_waves(self) -> None:
        calc = FibonacciCalculator()

        bullish = calc.calculate(
            WaveCount(
                pattern=WavePattern.IMPULSE,
                waves={
                    1: _wave(1, 0, 100.0, 1, 120.0),
                    3: _wave(3, 2, 110.0, 3, 150.0),
                    5: _wave(5, 4, 130.0, 5, 160.0),
                },
            )
        )
        bearish = calc.calculate(
            WaveCount(
                pattern=WavePattern.IMPULSE,
                waves={
                    1: _wave(1, 0, 120.0, 1, 100.0),
                    3: _wave(3, 2, 110.0, 3, 90.0),
                    5: _wave(5, 4, 95.0, 5, 80.0),
                },
            )
        )

        assert bullish.retracement[0.618] == 160.0 - (160.0 - 100.0) * 0.618
        assert bullish.extension[1.618] == 100.0 + 20.0 * 1.618
        assert any(level.label.startswith("0.618 retracement") for level in bullish.key_levels)
        assert bearish.retracement[0.5] == 80.0 + (120.0 - 80.0) * 0.5
        assert bearish.extension[1.0] == 120.0 - 20.0

    def test_calculate_corrective_for_upward_and_downward_a_wave(self) -> None:
        calc = FibonacciCalculator()

        downward = calc.calculate(
            WaveCount(
                pattern=WavePattern.CORRECTIVE,
                waves={-1: _wave(-1, 0, 120.0, 1, 100.0)},
            )
        )
        upward = calc.calculate(
            WaveCount(
                pattern=WavePattern.CORRECTIVE,
                waves={-1: _wave(-1, 0, 100.0, 1, 120.0)},
            )
        )
        missing_a = calc.calculate(WaveCount(pattern=WavePattern.CORRECTIVE))
        zero_amp = calc.calculate(
            WaveCount(pattern=WavePattern.CORRECTIVE, waves={-1: _wave(-1, 0, 100.0, 0, 100.0)})
        )

        assert downward.retracement[0.5] == 110.0
        assert downward.extension[1.0] == 100.0
        assert upward.retracement[0.5] == 110.0
        assert upward.extension[1.0] == 120.0
        assert missing_a == FibonacciLevels()
        assert zero_amp == FibonacciLevels()


class TestMeanReversionStrategyExtra:
    def test_on_init_sets_context_params(self) -> None:
        strategy = MeanReversionStrategy({"rsi_period": 10, "bb_period": 5})
        ctx = StrategyContext()

        strategy.on_init(ctx)

        assert ctx.params["rsi_period"] == 10
        assert ctx.params["bb_period"] == 5

    def test_bars_to_df_handles_empty_and_populates_symbol(self) -> None:
        strategy = MeanReversionStrategy()

        assert strategy._bars_to_df().empty

        strategy._bars = [_bar(0, 100.0), _bar(1, 101.0)]
        df = strategy._bars_to_df()

        assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume", "symbol"]
        assert df["symbol"].eq("BTC/USDT").all()

    def test_on_bar_returns_early_before_enough_bars_and_trims_history(self) -> None:
        strategy = MeanReversionStrategy({"bb_period": 3, "volume_period": 3, "rsi_period": 2})
        ctx = StrategyContext()

        with patch.object(strategy, "_bars_to_df", return_value=pd.DataFrame()) as bars_to_df:
            strategy.on_bar(ctx, _bar(0, 100.0))
            strategy.on_bar(ctx, _bar(1, 101.0))

        assert bars_to_df.call_count == 0

        strategy._max_bars = 3
        with (
            patch.object(strategy, "_bars_to_df", return_value=pd.DataFrame({"close": [1, 2, 3]})),
            patch.object(
                strategy,
                "generate_signals",
                return_value=(pd.Series(dtype=bool), pd.Series(dtype=bool)),
            ),
        ):
            for idx in range(5):
                strategy.on_bar(ctx, _bar(idx, 100.0 + idx))

        assert len(strategy._bars) == 3

    def test_on_bar_handles_empty_df_and_empty_entries(self) -> None:
        strategy = MeanReversionStrategy({"bb_period": 2, "volume_period": 2, "rsi_period": 2})
        ctx = StrategyContext()
        strategy._bars = [_bar(0, 100.0), _bar(1, 101.0)]

        with patch.object(strategy, "_bars_to_df", return_value=pd.DataFrame()):
            strategy.on_bar(ctx, _bar(2, 102.0))
        assert ctx.flush_signals() == []

        with (
            patch.object(strategy, "_bars_to_df", return_value=pd.DataFrame({"close": [100.0, 101.0]})),
            patch.object(
                strategy,
                "generate_signals",
                return_value=(pd.Series(dtype=bool), pd.Series(dtype=bool)),
            ),
        ):
            strategy.on_bar(ctx, _bar(3, 103.0))
        assert ctx.flush_signals() == []

    def test_on_bar_emits_long_short_and_flat_signals(self) -> None:
        strategy = MeanReversionStrategy({"bb_period": 2, "volume_period": 2, "rsi_period": 2})
        base_df = pd.DataFrame({"close": [100.0, 101.0, 102.0]})

        def run_case(rsi_value: float, entries_last: bool, exits_last: bool) -> list[Signal]:
            ctx = StrategyContext()
            strategy._bars = [_bar(0, 100.0), _bar(1, 101.0)]
            with (
                patch.object(strategy, "_bars_to_df", return_value=base_df),
                patch.object(
                    strategy,
                    "generate_signals",
                    return_value=(
                        pd.Series([False, False, entries_last], dtype=bool),
                        pd.Series([False, False, exits_last], dtype=bool),
                    ),
                ),
                patch.object(
                    strategy,
                    "_compute_rsi",
                    return_value=pd.Series([50.0, 50.0, rsi_value], dtype=float),
                ),
            ):
                strategy.on_bar(ctx, _bar(2, 102.0))
            return ctx.flush_signals()

        long_signals = run_case(20.0, True, False)
        short_signals = run_case(80.0, True, False)
        flat_signals = run_case(50.0, False, True)

        assert len(long_signals) == 1
        assert long_signals[0].direction == Direction.LONG
        assert len(short_signals) == 1
        assert short_signals[0].direction == Direction.SHORT
        assert len(flat_signals) == 1
        assert flat_signals[0].direction == Direction.FLAT
