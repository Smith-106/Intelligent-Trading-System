"""Tests for optimizer module — including GPSampler compatibility."""

from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd
import importlib.util

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

    cmaes_available = importlib.util.find_spec("cmaes") is not None

    @pytest.mark.skipif(
        not cmaes_available,
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

    def test_optimize_grid_uses_local_sweep_without_optuna_study(self, sample_data, monkeypatch):
        import optuna

        class _Engine:
            def run_backtest(
                self,
                close,
                entries,
                exits,
                initial_capital,
                fee,
            ):
                del close, entries, exits, initial_capital, fee

                class _Result:
                    sharpe_ratio = 1.0
                    sortino_ratio = 1.0
                    calmar_ratio = 1.0
                    total_return = 1.0

                return _Result()

        def _raise_create_study(*args, **kwargs):
            raise AssertionError("grid search should not create an Optuna study")

        def signal_fn(close_series, **params):
            assert params
            empty = pd.Series(False, index=close_series.index)
            return empty, empty

        monkeypatch.setattr(optuna, "create_study", _raise_create_study)

        optimizer = StrategyOptimizer(engine=cast(Any, _Engine()))
        result = optimizer.optimize(
            close=sample_data,
            signal_fn=signal_fn,
            param_space={"threshold": (0.0, 0.05)},
            n_trials=3,
            method="grid",
        )

        assert result["method"] == "grid"
        assert result["n_trials"] == 3

    def test_grid_candidates_cover_multi_parameter_space(self):
        candidates = StrategyOptimizer._grid_candidates(
            {"fast": (1, 5), "slow": (10, 50)},
            n_trials=3,
        )

        assert candidates == [
            {"fast": 1, "slow": 10},
            {"fast": 3, "slow": 30},
            {"fast": 5, "slow": 50},
        ]

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

    def test_optimize_unknown_objective_falls_back_to_sharpe(self):
        class _Engine:
            def run_backtest(
                self,
                close,
                entries,
                exits,
                initial_capital,
                fee,
            ):
                class _Result:
                    sharpe_ratio = 1.23
                    sortino_ratio = 4.56
                    calmar_ratio = 7.89
                    total_return = 9.87

                return _Result()

        close = pd.Series([100.0, 101.0, 102.0], dtype=float)

        def fn(close_series, **params):
            del params
            empty = pd.Series(False, index=close_series.index)
            return empty, empty

        optimizer = StrategyOptimizer(engine=cast(Any, _Engine()))
        result = optimizer.optimize(
            close=close,
            signal_fn=fn,
            param_space={"threshold": (0, 0)},
            n_trials=1,
            objective="unknown-objective",
        )

        assert result["best_value"] == pytest.approx(1.23)
        assert result["objective"] == "unknown-objective"

    def test_optimize_downgrades_trial_exceptions(self):
        class _Engine:
            def run_backtest(
                self,
                close,
                entries,
                exits,
                initial_capital,
                fee,
            ):
                raise RuntimeError("boom")

        close = pd.Series([100.0, 101.0, 102.0], dtype=float)

        def fn(close_series, **params):
            del params
            empty = pd.Series(False, index=close_series.index)
            return empty, empty

        optimizer = StrategyOptimizer(engine=cast(Any, _Engine()))
        result = optimizer.optimize(
            close=close,
            signal_fn=fn,
            param_space={"threshold": (0, 0)},
            n_trials=1,
        )

        assert result["best_value"] == -10.0

    def test_create_sampler_bayesian_falls_back_to_tpe_on_error(self, monkeypatch):
        import optuna

        def _raise_runtime_error():
            raise RuntimeError("gps unavailable")

        monkeypatch.setattr(optuna.samplers, "GPSampler", _raise_runtime_error)

        sampler = StrategyOptimizer._create_sampler("bayesian")

        assert isinstance(sampler, optuna.samplers.TPESampler)
