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

        with patch.object(
            calc, "calculate", return_value=FibonacciLevels(retracement={0.5: 100.0})
        ):
            result = calc.compute(df, wave_count=wave_count)

        assert result.isna().all()

    def test_calculate_handles_unknown_missing_w1_and_zero_amplitude_impulse(self) -> None:
        calc = FibonacciCalculator()

        unknown = calc.calculate(WaveCount(pattern=WavePattern.UNKNOWN))
        missing_w1 = calc.calculate(
            WaveCount(pattern=WavePattern.IMPULSE, waves={3: _wave(3, 1, 110.0, 2, 120.0)})
        )
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

        with patch.object(strategy, "_latest_signal", return_value=(None, False)):
            strategy.on_bar(ctx, _bar(2, 102.0))
        assert ctx.flush_signals() == []

        with patch.object(strategy, "_latest_signal", return_value=(None, False)):
            strategy.on_bar(ctx, _bar(3, 103.0))
        assert ctx.flush_signals() == []

    def test_on_bar_emits_long_short_and_flat_signals(self) -> None:
        strategy = MeanReversionStrategy({"bb_period": 2, "volume_period": 2, "rsi_period": 2})

        def run_case(
            entry_direction: Direction | None,
            exits_last: bool,
            *,
            in_position: bool = False,
            entry_direction_state: Direction | None = None,
        ) -> list[Signal]:
            ctx = StrategyContext()
            strategy._bars = [_bar(0, 100.0), _bar(1, 101.0)]
            strategy._in_position = in_position
            strategy._entry_direction = entry_direction_state
            with patch.object(
                strategy,
                "_latest_signal",
                return_value=(entry_direction, exits_last),
            ):
                strategy.on_bar(ctx, _bar(2, 102.0))
            return ctx.flush_signals()

        long_signals = run_case(Direction.LONG, False)
        short_signals = run_case(Direction.SHORT, False)
        # For exit, simulate being in a LONG position
        flat_signals = run_case(None, True, in_position=True, entry_direction_state=Direction.LONG)

        assert len(long_signals) == 1
        assert long_signals[0].direction == Direction.LONG
        assert len(short_signals) == 1
        assert short_signals[0].direction == Direction.SHORT
        assert len(flat_signals) == 1
        assert flat_signals[0].direction == Direction.FLAT

    def test_stop_loss_triggers_on_bar_long(self) -> None:
        """ISS-20260720-003: stop_loss_pct triggers exit when unrealized loss exceeds threshold."""
        strategy = MeanReversionStrategy(
            {"bb_period": 2, "volume_period": 2, "rsi_period": 2, "stop_loss_pct": 0.05}
        )
        ctx = StrategyContext()
        # Pre-fill bars so we pass the bb_period check
        strategy._bars = [_bar(0, 100.0), _bar(1, 101.0)]
        # Simulate a LONG entry at 100.0
        strategy._in_position = True
        strategy._entry_direction = Direction.LONG
        strategy._entry_price = 100.0
        strategy._bars_since_entry = 0
        # Price drops to 94.0 (6% loss, exceeds 5% stop loss)
        with patch.object(strategy, "_latest_signal", return_value=(None, False)):
            strategy.on_bar(ctx, _bar(2, 94.0))
        signals = ctx.flush_signals()
        # Should emit a FLAT exit signal due to stop loss
        assert len(signals) == 1
        assert signals[0].direction == Direction.FLAT
        assert signals[0].strength == 0.8  # stop loss uses higher strength
        assert not strategy._in_position

    def test_stop_loss_triggers_on_bar_short(self) -> None:
        """ISS-20260720-003: stop_loss_pct triggers exit for SHORT when price rises."""
        strategy = MeanReversionStrategy(
            {"bb_period": 2, "volume_period": 2, "rsi_period": 2, "stop_loss_pct": 0.05}
        )
        ctx = StrategyContext()
        strategy._bars = [_bar(0, 100.0), _bar(1, 99.0)]
        strategy._in_position = True
        strategy._entry_direction = Direction.SHORT
        strategy._entry_price = 100.0
        strategy._bars_since_entry = 0
        # Price rises to 106.0 (6% loss, exceeds 5% stop loss)
        with patch.object(strategy, "_latest_signal", return_value=(None, False)):
            strategy.on_bar(ctx, _bar(2, 106.0))
        signals = ctx.flush_signals()
        assert len(signals) == 1
        assert signals[0].direction == Direction.FLAT
        assert not strategy._in_position

    def test_stop_loss_not_triggered_within_threshold(self) -> None:
        """ISS-20260720-003: stop_loss does NOT trigger when loss is within threshold."""
        strategy = MeanReversionStrategy(
            {"bb_period": 2, "volume_period": 2, "rsi_period": 2, "stop_loss_pct": 0.05}
        )
        ctx = StrategyContext()
        strategy._bars = [_bar(0, 100.0), _bar(1, 101.0)]
        strategy._in_position = True
        strategy._entry_direction = Direction.LONG
        strategy._entry_price = 100.0
        strategy._bars_since_entry = 0
        # Price drops to 96.0 (4% loss, within 5% stop loss)
        with patch.object(strategy, "_latest_signal", return_value=(None, False)):
            strategy.on_bar(ctx, _bar(2, 96.0))
        signals = ctx.flush_signals()
        # No stop loss signal — still within threshold
        flat_signals = [s for s in signals if s.direction == Direction.FLAT and s.strength == 0.8]
        assert len(flat_signals) == 0
        assert strategy._in_position  # Still in position

    def test_stop_loss_disabled_when_zero(self) -> None:
        """ISS-20260720-003: stop_loss_pct=0 (default) disables stop loss."""
        strategy = MeanReversionStrategy({"bb_period": 2, "volume_period": 2, "rsi_period": 2})
        assert strategy._stop_loss_pct == 0.0

    def test_stop_loss_exit_series_vectorized(self) -> None:
        """ISS-20260720-003: _stop_loss_exit_series produces correct boolean exits."""
        close = pd.Series([100.0, 98.0, 94.0, 96.0, 90.0])
        entries = pd.Series([True, False, False, False, False])
        # 5% stop loss: entry at 100, stop at 95
        exits = MeanReversionStrategy._stop_loss_exit_series(close, entries, 0.05, direction=1)
        assert not exits.iloc[0]  # entry bar, no exit
        assert not exits.iloc[1]  # 98 > 95, no stop
        assert exits.iloc[2]  # 94 <= 95, stop triggered
        assert not exits.iloc[3]  # position already closed
        assert not exits.iloc[4]  # position already closed
