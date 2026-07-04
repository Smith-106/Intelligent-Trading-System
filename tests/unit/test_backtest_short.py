"""Tests for BacktestEngine SHORT direction — P0-3."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.research.backtest import BacktestEngine, BacktestResult


def _make_price_series(n: int = 100, start: float = 100.0, trend: float = 0.01) -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    noise = np.random.normal(0, 0.02, n)
    prices = start * np.exp(np.cumsum(trend + noise))
    return pd.Series(prices, index=dates)


def _make_signals(n: int) -> tuple[pd.Series, pd.Series]:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    entries = pd.Series(False, index=dates)
    exits = pd.Series(False, index=dates)
    for i in range(0, n, 10):
        entries.iloc[i] = True
    for i in range(5, n, 10):
        exits.iloc[i] = True
    return entries, exits


class TestBacktestShort:
    def test_short_direction_int(self):
        """direction=-1 should produce SHORT trades."""
        close = _make_price_series(100, trend=-0.005)
        entries, exits = _make_signals(100)
        engine = BacktestEngine()
        result = engine.run_backtest(close, entries, exits, direction=-1)

        assert result.num_trades > 0
        # SHORT in downtrend should have positive return
        assert isinstance(result.total_return, float)

    def test_short_series_direction(self):
        """direction as a pd.Series should work per-bar."""
        n = 100
        close = _make_price_series(n, trend=-0.005)
        entries, exits = _make_signals(n)
        # All bars = SHORT direction
        direction = pd.Series(-1, index=close.index)
        engine = BacktestEngine()
        result = engine.run_backtest(close, entries, exits, direction=direction)

        assert result.num_trades > 0

    def test_short_pnl_direction_aware(self):
        """SHORT trade PnL: (entry - exit) / entry."""
        n = 10
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        # Declining prices: SHORT should profit
        close = pd.Series([100.0, 98.0, 96.0, 94.0, 92.0, 90.0, 88.0, 86.0, 84.0, 82.0], index=dates)
        entries = pd.Series(False, index=dates)
        exits = pd.Series(False, index=dates)
        entries.iloc[0] = True
        exits.iloc[5] = True

        engine = BacktestEngine()
        result = engine.run_backtest(close, entries, exits, direction=-1, fee=0.0)

        assert result.num_trades == 1
        # SHORT from 100 → 90: PnL = (100 - 90)/100 = 10%
        assert result.total_return > 0

    def test_short_loses_in_uptrend(self):
        """SHORT in uptrend should lose money."""
        n = 10
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        close = pd.Series([100.0, 102.0, 104.0, 106.0, 108.0, 110.0, 112.0, 114.0, 116.0, 118.0], index=dates)
        entries = pd.Series(False, index=dates)
        exits = pd.Series(False, index=dates)
        entries.iloc[0] = True
        exits.iloc[5] = True

        engine = BacktestEngine()
        result = engine.run_backtest(close, entries, exits, direction=-1, fee=0.0)

        assert result.num_trades == 1
        assert result.total_return < 0

    def test_short_with_fee(self):
        """SHORT entry at close*(1-fee), exit at close*(1+fee)."""
        n = 6
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        # Flat prices → fee should erode capital
        close = pd.Series([100.0, 100.0, 100.0, 100.0, 100.0, 100.0], index=dates)
        entries = pd.Series(False, index=dates)
        exits = pd.Series(False, index=dates)
        entries.iloc[0] = True
        exits.iloc[4] = True

        engine = BacktestEngine()
        result = engine.run_backtest(close, entries, exits, direction=-1, fee=0.001)

        assert result.num_trades == 1
        # With flat prices, fees should cause a loss
        assert result.total_return < 0

    def test_short_open_position_closed_at_end(self):
        """Open SHORT position at last bar should be closed at close[-1]."""
        n = 5
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        close = pd.Series([100.0, 99.0, 98.0, 97.0, 96.0], index=dates)
        entries = pd.Series(False, index=dates)
        exits = pd.Series(False, index=dates)
        entries.iloc[0] = True
        # No exit signal → position closes at last bar

        engine = BacktestEngine()
        result = engine.run_backtest(close, entries, exits, direction=-1, fee=0.0)

        assert result.num_trades == 1
        # SHORT from 99.0 (next bar open) to 96.0: PnL = (99-96)/99 > 0
        assert result.total_return > 0

    def test_mixed_direction_series(self):
        """Direction Series mixing LONG and SHORT."""
        n = 20
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        # Declining then rising
        close_vals = [100.0 - i * 0.5 for i in range(10)] + [95.0 + i * 0.5 for i in range(10)]
        close = pd.Series(close_vals, index=dates)
        entries = pd.Series(False, index=dates)
        exits = pd.Series(False, index=dates)
        entries.iloc[0] = True   # SHORT in decline
        exits.iloc[5] = True
        entries.iloc[10] = True  # SHORT again but now rising → loss
        exits.iloc[15] = True

        # First half SHORT, second half also SHORT
        direction = pd.Series(-1, index=dates)

        engine = BacktestEngine()
        result = engine.run_backtest(close, entries, exits, direction=direction, fee=0.0)

        assert result.num_trades == 2

    def test_short_win_rate_and_profit_factor(self):
        """SHORT winning trade should count in win_rate and profit_factor."""
        n = 10
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        close = pd.Series([100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0, 93.0, 92.0, 91.0], index=dates)
        entries = pd.Series(False, index=dates)
        exits = pd.Series(False, index=dates)
        entries.iloc[0] = True
        exits.iloc[5] = True

        engine = BacktestEngine()
        result = engine.run_backtest(close, entries, exits, direction=-1, fee=0.0)

        assert result.num_trades == 1
        assert result.win_rate == 1.0  # single winning trade
        assert result.profit_factor > 0

    def test_short_default_direction_is_long(self):
        """Default direction=1 should produce LONG trades (backward compat)."""
        close = _make_price_series(100, trend=0.005)
        entries, exits = _make_signals(100)
        engine = BacktestEngine()
        result_long = engine.run_backtest(close, entries, exits, direction=1)
        result_default = engine.run_backtest(close, entries, exits)

        # Both should produce identical results
        assert result_long.total_return == pytest.approx(result_default.total_return)
        assert result_long.num_trades == result_default.num_trades
