"""Tests for quantflow.signal.risk_metrics."""

import numpy as np
import pandas as pd

from quantflow.signal.risk_metrics import (
    conditional_var,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
    value_at_risk,
)


class TestValueAtRisk:
    def test_historical_var(self):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.001, 0.02, 1000))
        var = value_at_risk(returns, confidence=0.95)
        # VaR is returned as a negative fraction (loss)
        assert var < 0

    def test_parametric_var(self):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.001, 0.02, 1000))
        var = value_at_risk(returns, confidence=0.95, method="parametric")
        assert var < 0

    def test_insufficient_data(self):
        returns = pd.Series([0.01])
        assert value_at_risk(returns) == 0.0


class TestConditionalVar:
    def test_cvar_worse_than_var(self):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.001, 0.02, 1000))
        var = value_at_risk(returns)
        cvar = conditional_var(returns)
        # CVaR magnitude should be >= VaR magnitude (both negative)
        assert abs(cvar) >= abs(var)


class TestMaxDrawdown:
    def test_positive_curve(self):
        equity = pd.Series([100, 110, 120, 130, 140])
        dd = max_drawdown(equity)
        assert dd == 0.0

    def test_drawdown_curve(self):
        equity = pd.Series([100, 120, 90, 110])
        dd = max_drawdown(equity)
        assert dd < 0
        assert abs(dd - (-0.25)) < 0.01

    def test_short_series(self):
        assert max_drawdown(pd.Series([100])) == 0.0


class TestSharpeRatio:
    def test_positive_sharpe(self):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.002, 0.01, 252))
        sr = sharpe_ratio(returns)
        assert sr > 0

    def test_zero_std(self):
        returns = pd.Series([0.0] * 100)
        assert sharpe_ratio(returns) == 0.0


class TestSortinoRatio:
    def test_positive_sortino(self):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.002, 0.01, 252))
        so = sortino_ratio(returns)
        assert so > 0

    def test_sortino_returns_zero_for_single_observation(self):
        assert sortino_ratio(pd.Series([0.01])) == 0.0
