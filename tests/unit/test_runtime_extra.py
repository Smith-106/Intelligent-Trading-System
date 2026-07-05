"""Additional _runtime helper tests — covers lines 41, 49, 68."""

import pandas as pd
import pytest

from quantflow.common.models import Bar
from quantflow.strategy.templates._runtime import (
    closes,
    ewm_series,
    highs,
    lows,
    profit_target_exit,
    rolling_mean_optional_at,
    rolling_std_at,
    simple_rsi_last,
    true_range_value,
    true_ranges,
    volumes,
)


class TestRollingStdAtShortWindow:
    def test_window_length_less_than_2_returns_none(self):
        """Line 41: len(window) < 2 → None."""
        # period=1 → window of 1 element → None
        assert rolling_std_at([100.0, 101.0, 102.0], 0, 1) is None

    def test_period_0_returns_none(self):
        assert rolling_std_at([1.0], 0, 0) is None

    def test_valid_std(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = rolling_std_at(vals, 4, 3)
        assert result is not None
        assert result > 0


class TestEwmSeriesEmpty:
    def test_empty_input(self):
        """Line 49: empty values → return []."""
        assert ewm_series([], 5) == []

    def test_single_value(self):
        assert ewm_series([42.0], 3) == [42.0]


class TestSimpleRsiLastShort:
    def test_period_0_returns_none(self):
        """Line 67 (closely related): period <= 0."""
        assert simple_rsi_last([1.0, 2.0, 3.0], 0) is None

    def test_insufficient_values(self):
        """Line 68: len(values) < period + 1."""
        assert simple_rsi_last([1.0], 5) is None

    def test_all_losses(self):
        vals = [110.0, 109.0, 108.0, 107.0, 106.0, 105.0, 104.0]
        result = simple_rsi_last(vals, 5)
        assert result is not None
        assert result < 30  # very oversold


class TestTrueRangeValue:
    def test_no_previous_close(self):
        """Line 85-86: previous_close is None."""
        assert true_range_value(105.0, 95.0, 100.0, None) == 10.0

    def test_with_previous_close(self):
        assert true_range_value(105.0, 95.0, 100.0, 97.0) == 10.0  # max(10, 8, 2) = 10

    def test_gap_up(self):
        # high-low=5, high-prev_close=8, low-prev_close=3 → max=8
        assert true_range_value(108.0, 103.0, 107.0, 100.0) == 8.0


class TestTrueRanges:
    def test_basic(self):
        result = true_ranges([105.0, 110.0], [95.0, 100.0], [100.0, 108.0])
        assert len(result) == 2
        assert result[0] == 10.0  # first bar: high - low
        # second: max(10, |110-100|, |100-100|) = max(10, 10, 0) = 10
        assert result[1] == 10.0


class TestBarHelpers:
    def test_closes(self):
        bars = [Bar("BTC", 1, 100, 101, 99, 100.5, 1000), Bar("BTC", 2, 100, 102, 98, 101, 1000)]
        assert closes(bars) == [100.5, 101.0]

    def test_highs(self):
        bars = [Bar("BTC", 1, 100, 105, 99, 100, 1000)]
        assert highs(bars) == [105.0]

    def test_lows(self):
        bars = [Bar("BTC", 1, 100, 101, 95, 100, 1000)]
        assert lows(bars) == [95.0]

    def test_volumes(self):
        bars = [Bar("BTC", 1, 100, 101, 99, 100, 2000)]
        assert volumes(bars) == [2000.0]


class TestRollingMeanOptionalAt:
    def test_with_none_in_window(self):
        """Line 125: any value is None → return None."""
        assert rolling_mean_optional_at([1.0, None, 3.0], 2, 3) is None

    def test_valid(self):
        assert rolling_mean_optional_at([1.0, 2.0, 3.0], 2, 3) == pytest.approx(2.0)

    def test_period_too_large(self):
        assert rolling_mean_optional_at([1.0], 0, 5) is None


class TestProfitTargetExitShort:
    def test_short_direction_profit_exit(self):
        """Lines 174-178: SHORT direction profit target exit."""
        close = pd.Series([100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0, 93.0, 92.0, 91.0])
        entries = pd.Series(False, index=close.index)
        entries.iloc[0] = True

        result = profit_target_exit(close, entries, 0.05, 100, direction=-1)
        # SHORT: target = 100 * (1 - 0.05) = 95
        # close[5]=95 → exit!
        assert bool(result.iloc[5]) or bool(result.iloc[4])  # exact boundary

    def test_long_direction_profit_exit(self):
        close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0])
        entries = pd.Series(False, index=close.index)
        entries.iloc[0] = True

        result = profit_target_exit(close, entries, 0.05, 100, direction=1)
        # LONG: target = 100 * 1.05 = 105
        # close[5]=105 → exit
        assert bool(result.iloc[5])

    def test_max_holding_bars_exit(self):
        close = pd.Series([100.0] * 20)
        entries = pd.Series(False, index=close.index)
        entries.iloc[0] = True

        result = profit_target_exit(close, entries, 1.0, 5)  # 100% profit target → never triggers
        # Max holding = 5, so exit at bar 5
        assert bool(result.iloc[5])
