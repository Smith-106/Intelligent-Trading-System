"""Tests for optimizer.py uncovered paths — grid sampling, objective values, edge cases."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from quantflow.strategy.research.optimizer import StrategyOptimizer


class TestOptimizerObjectiveValue:
    def test_sharpe_objective(self):
        result = MagicMock()
        result.sharpe_ratio = 1.5
        assert StrategyOptimizer._objective_value(result, "sharpe") == 1.5

    def test_sortino_objective(self):
        result = MagicMock()
        result.sortino_ratio = 2.0
        assert StrategyOptimizer._objective_value(result, "sortino") == 2.0

    def test_calmar_objective(self):
        result = MagicMock()
        result.calmar_ratio = 1.8
        assert StrategyOptimizer._objective_value(result, "calmar") == 1.8

    def test_return_objective(self):
        result = MagicMock()
        result.total_return = 0.25
        assert StrategyOptimizer._objective_value(result, "return") == 0.25

    def test_win_rate_objective(self):
        result = MagicMock()
        result.win_rate = 0.6
        assert StrategyOptimizer._objective_value(result, "win_rate") == 0.6

    def test_unknown_objective_defaults_to_sharpe(self):
        result = MagicMock()
        result.sharpe_ratio = 1.2
        assert StrategyOptimizer._objective_value(result, "unknown") == 1.2


class TestGridCandidates:
    def test_n_trials_less_than_1_returns_empty(self):
        """Line 170: n_trials < 1 → return []."""
        result = StrategyOptimizer._grid_candidates({"a": (1, 10)}, 0)
        assert result == []

    def test_empty_param_space(self):
        """Line 172: no param_space → return [{}]."""
        result = StrategyOptimizer._grid_candidates({}, 5)
        assert result == [{}]

    def test_total_candidates_within_n_trials(self):
        """Small total combinations → return all combos."""
        result = StrategyOptimizer._grid_candidates({"a": (1, 2), "b": (3, 4)}, 10)
        assert len(result) == 4  # 2*2=4 < 10

    def test_total_candidates_exceeds_n_trials(self):
        """Large total → sampled grid with n_trials candidates."""
        result = StrategyOptimizer._grid_candidates(
            {"a": tuple(range(100)), "b": tuple(range(100))},
            5,
        )
        assert len(result) == 5

    def test_single_trial(self):
        """n_trials=1 → single candidate (index 0)."""
        result = StrategyOptimizer._grid_candidates({"a": (1, 10), "b": (1, 10)}, 1)
        assert len(result) == 1


class TestGridValues:
    def test_spec_more_than_2_values(self):
        """Line 195: spec with >2 values → return as list, capped at n_trials."""
        spec = (1, 2, 3, 4, 5, 6, 7, 8)
        result = StrategyOptimizer._grid_values(spec, 3)
        assert len(result) == 3
        assert result == [1, 2, 3]

    def test_int_range_with_span_zero(self):
        """Lines 205-206: int range where high==low → return [low]."""
        result = StrategyOptimizer._grid_values((5, 5), 3)
        assert result == [5]

    def test_int_range_single_trial(self):
        """Line 201: n_trials==1 → return [low]."""
        result = StrategyOptimizer._grid_values((1, 10), 1)
        assert result == [1]

    def test_int_range_step_greater_than_span(self):
        """Int step > span → returns [low, high]."""
        result = StrategyOptimizer._grid_values((1, 3), 10)
        # step = max(1, round(2/9)) = 1, range(1,4,1) = [1,2,3]
        assert 1 in result
        assert 3 in result

    def test_float_range_single_trial(self):
        """Line 213: n_trials==1 → return [float(low)]."""
        result = StrategyOptimizer._grid_values((0.1, 0.9), 1)
        assert result == [pytest.approx(0.1)]

    def test_float_range_equal_bounds(self):
        """Line 216: low_float == high_float → return [low_float]."""
        result = StrategyOptimizer._grid_values((0.5, 0.5), 3)
        assert result == [0.5]

    def test_float_range_with_step(self):
        """Normal float range → linspace-like values."""
        result = StrategyOptimizer._grid_values((0.0, 1.0), 3)
        assert len(result) == 3
        assert result[0] == pytest.approx(0.0)
        assert result[2] == pytest.approx(1.0)


class TestOptimizerOptimize:
    def test_optimize_grid_method(self):
        """Grid method produces results without optuna."""
        engine_mock = MagicMock()
        engine_mock.run_backtest.return_value = MagicMock(
            sharpe_ratio=1.0,
            sortino_ratio=1.2,
            calmar_ratio=0.9,
            total_return=0.1,
            win_rate=0.55,
        )
        optimizer = StrategyOptimizer(engine=engine_mock)
        close = pd.Series([100.0 + i * 0.5 for i in range(50)])
        entries = pd.Series(False, index=close.index)
        entries.iloc[10] = True

        def signal_fn(data, **params):
            e = pd.Series(False, index=data.index)
            x = pd.Series(False, index=data.index)
            return e, x

        result = optimizer.optimize(
            close,
            signal_fn,
            {"period": (2, 10)},
            n_trials=3,
            method="grid",
        )
        assert "best_params" in result
        assert "best_value" in result

    def test_optimize_bayesian_with_optuna(self):
        """Bayesian method uses optuna (lazy imported)."""
        engine_mock = MagicMock()
        engine_mock.run_backtest.return_value = MagicMock(
            sharpe_ratio=0.5,
            sortino_ratio=0.6,
            calmar_ratio=0.4,
            total_return=0.05,
            win_rate=0.5,
        )
        optimizer = StrategyOptimizer(engine=engine_mock)
        close = pd.Series([100.0 + i * 0.5 for i in range(50)])

        def signal_fn(data, **params):
            return pd.Series(False, index=data.index), pd.Series(False, index=data.index)

        # Patch optuna at import site inside _create_sampler
        import optuna

        mock_study = MagicMock()
        mock_study.optimize = MagicMock()
        mock_study.best_params = {"period": 5}
        mock_study.best_value = 0.5
        with patch.object(optuna, "create_study", return_value=mock_study):
            result = optimizer.optimize(
                close,
                signal_fn,
                {"period": (2, 10)},
                n_trials=3,
                method="bayesian",
            )
        assert "best_params" in result
