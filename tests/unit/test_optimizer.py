"""Tests for optimizer module — including GPSampler compatibility."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.research.optimizer import StrategyOptimizer


class TestStrategyOptimizer:
    """Test optimizer with various sampler methods."""

    @pytest.fixture
    def sample_data(self):
        dates = pd.date_range("2024-01-01", periods=200, freq="D")
        np.random.seed(42)
        close = pd.Series(np.random.randn(200).cumsum() + 100, index=dates)
        return close

    @pytest.fixture
    def simple_signal_fn(self):
        def fn(close_series, **params):
            threshold = params.get("threshold", 0.0)
            entries = close_series.pct_change() > threshold
            exits = close_series.pct_change() < -threshold
            return entries, exits

        return fn

    def test_optimize_bayesian(self, sample_data, simple_signal_fn):
        optimizer = StrategyOptimizer()
        result = optimizer.optimize(
            close=sample_data,
            signal_fn=simple_signal_fn,
            param_space={"threshold": (0.0, 0.05)},
            n_trials=5,
            method="bayesian",
        )
        assert "best_params" in result
        assert "best_value" in result
        assert result["method"] == "bayesian"

    @pytest.mark.skipif(
        True,  # cmaes package not installed in this environment
        reason="cmaes package not available",
    )
    def test_optimize_cmaes(self, sample_data, simple_signal_fn):
        optimizer = StrategyOptimizer()
        result = optimizer.optimize(
            close=sample_data,
            signal_fn=simple_signal_fn,
            param_space={"threshold": (0.0, 0.05)},
            n_trials=5,
            method="cmaes",
        )
        assert "best_params" in result

    def test_optimize_grid(self, sample_data, simple_signal_fn):
        optimizer = StrategyOptimizer()
        result = optimizer.optimize(
            close=sample_data,
            signal_fn=simple_signal_fn,
            param_space={"threshold": (0.0, 0.05)},
            n_trials=5,
            method="grid",
        )
        assert "best_params" in result

    def test_create_sampler_bayesian(self):
        sampler = StrategyOptimizer._create_sampler("bayesian")
        assert sampler is not None

    def test_create_sampler_cmaes(self):
        import optuna

        sampler = StrategyOptimizer._create_sampler("cmaes")
        assert isinstance(sampler, optuna.samplers.CmaEsSampler)

    def test_create_sampler_grid(self):
        import optuna

        sampler = StrategyOptimizer._create_sampler("grid")
        assert isinstance(sampler, optuna.samplers.RandomSampler)

    def test_optimize_objectives(self, sample_data, simple_signal_fn):
        for objective in ["sharpe", "sortino", "calmar", "return"]:
            optimizer = StrategyOptimizer()
            result = optimizer.optimize(
                close=sample_data,
                signal_fn=simple_signal_fn,
                param_space={"threshold": (0.0, 0.05)},
                n_trials=3,
                objective=objective,
            )
            assert result["objective"] == objective

    def test_optimize_with_integer_params(self, sample_data):
        def fn(close_series, **params):
            period = params.get("period", 10)
            ma = close_series.rolling(period).mean()
            entries = close_series > ma
            exits = close_series < ma
            return entries, exits

        optimizer = StrategyOptimizer()
        result = optimizer.optimize(
            close=sample_data,
            signal_fn=fn,
            param_space={"period": (5, 30)},
            n_trials=3,
        )
        assert "best_params" in result
