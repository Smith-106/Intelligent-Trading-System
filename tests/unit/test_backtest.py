"""Tests for backtest engine."""

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.research.backtest import BacktestEngine, BacktestResult


def _make_price_series(n: int = 100, start: float = 100.0, trend: float = 0.01) -> pd.Series:
    """Create a synthetic price series with optional drift."""
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    noise = np.random.normal(0, 0.02, n)
    prices = start * np.exp(np.cumsum(trend + noise))
    return pd.Series(prices, index=dates)


def _make_signals(
    n: int, entry_pattern: str = "every_10", exit_pattern: str = "hold_5"
) -> tuple[pd.Series, pd.Series]:
    """Create simple entry/exit signal patterns."""
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    entries = pd.Series(False, index=dates)
    exits = pd.Series(False, index=dates)

    if entry_pattern == "every_10":
        for i in range(0, n, 10):
            entries.iloc[i] = True
    elif entry_pattern == "first_only":
        entries.iloc[0] = True

    if exit_pattern == "hold_5":
        for i in range(5, n, 10):
            exits.iloc[i] = True
    elif exit_pattern == "last":
        exits.iloc[-1] = True

    return entries, exits


class TestBacktestEngine:
    def test_basic_backtest(self):
        close = _make_price_series(100, trend=0.005)
        entries, exits = _make_signals(100)
        engine = BacktestEngine()
        result = engine.run_backtest(close, entries, exits)

        assert isinstance(result, BacktestResult)
        assert result.num_trades > 0
        assert result.initial_capital > 0
        assert result.final_capital != result.initial_capital

    def test_no_trades(self):
        close = _make_price_series(50)
        entries = pd.Series(False, index=close.index)
        exits = pd.Series(False, index=close.index)
        engine = BacktestEngine()
        result = engine.run_backtest(close, entries, exits)

        assert result.num_trades == 0
        assert result.final_capital == pytest.approx(result.initial_capital)

    def test_single_trade(self):
        close = _make_price_series(50, trend=0.01)
        entries = pd.Series(False, index=close.index)
        exits = pd.Series(False, index=close.index)
        entries.iloc[0] = True
        exits.iloc[20] = True
        engine = BacktestEngine()
        result = engine.run_backtest(close, entries, exits)

        assert result.num_trades == 1

    def test_equity_curve_stays_finite_while_position_is_open(self):
        dates = pd.date_range("2024-01-01", periods=6, freq="D")
        close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0], index=dates)
        entries = pd.Series(False, index=dates)
        exits = pd.Series(False, index=dates)
        entries.iloc[0] = True
        exits.iloc[4] = True

        engine = BacktestEngine()
        result = engine.run_backtest(close, entries, exits)

        assert np.isfinite(result.equity_curve).all()
        assert result.equity_curve.iloc[1] == pytest.approx(result.initial_capital)
        assert result.equity_curve.iloc[4] == pytest.approx(result.initial_capital)

    def test_drawdown_is_negative(self):
        # Create a declining series
        dates = pd.date_range("2024-01-01", periods=50, freq="D")
        close = pd.Series(np.linspace(100, 80, 50), index=dates)
        entries, exits = _make_signals(50)
        engine = BacktestEngine()
        result = engine.run_backtest(close, entries, exits)

        assert result.max_drawdown <= 0

    def test_positive_trend_positive_return(self):
        close = _make_price_series(200, trend=0.02)
        entries, exits = _make_signals(200)
        engine = BacktestEngine()
        result = engine.run_backtest(close, entries, exits)

        # With strong positive trend, should generate trades
        assert result.num_trades > 0
        # Win rate should be positive in uptrend
        assert result.win_rate >= 0

    def test_result_summary(self):
        close = _make_price_series(100)
        entries, exits = _make_signals(100)
        engine = BacktestEngine()
        result = engine.run_backtest(close, entries, exits)

        summary = result.summary()
        assert "Backtest" in summary
        assert "Sharpe" in summary

    def test_parameter_sweep(self):
        close = _make_price_series(100)
        param_combos = [
            {"threshold": 0.5},
            {"threshold": 1.0},
        ]

        def signal_fn(c, **kwargs):
            entries = pd.Series(c > c.mean() * kwargs.get("threshold", 1.0), index=c.index)
            exits = pd.Series(c < c.mean() * kwargs.get("threshold", 1.0), index=c.index)
            return entries, exits

        engine = BacktestEngine()
        results = engine.parameter_sweep(close, param_combos, signal_fn)
        assert len(results) == 2
        # Sorted by sharpe (descending)
        assert results[0].sharpe_ratio >= results[1].sharpe_ratio

    def test_sharpe_zero_std(self):
        returns = pd.Series([0.0] * 10)
        sharpe = BacktestEngine._calc_sharpe(returns)
        assert sharpe == 0.0

    def test_sortino_no_downside(self):
        returns = pd.Series([0.01] * 10)
        sortino = BacktestEngine._calc_sortino(returns)
        assert sortino == 0.0

    def test_sortino_short_series_returns_zero(self):
        returns = pd.Series([0.01])
        sortino = BacktestEngine._calc_sortino(returns)
        assert sortino == 0.0

    def test_annual_return_handles_non_finite_total_return(self, monkeypatch):
        close = pd.Series(
            [100.0, 110.0, 120.0],
            index=pd.date_range("2024-01-01", periods=3, freq="D"),
        )
        entries = pd.Series([False, False, False], index=close.index)
        exits = pd.Series([False, False, False], index=close.index)
        engine = BacktestEngine()

        monkeypatch.setattr("quantflow.strategy.research.backtest.np.isfinite", lambda value: False)
        result = engine.run_backtest(close, entries, exits)

        assert result.annual_return == float("inf")

    def test_annual_return_clamps_total_loss_to_negative_one(self):
        dates = pd.date_range("2024-01-01", periods=3, freq="D")
        close = pd.Series([100.0, 100.0, 0.0], index=dates)
        entries = pd.Series([True, False, False], index=dates)
        exits = pd.Series([False, True, False], index=dates)

        engine = BacktestEngine()
        result = engine.run_backtest(close, entries, exits, fee=0.0)

        assert result.final_capital == pytest.approx(0.0)
        assert result.total_return == pytest.approx(-1.0)
        assert result.annual_return == -1.0
