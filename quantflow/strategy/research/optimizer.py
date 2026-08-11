"""Parameter optimization with Optuna samplers and local grid search."""

from __future__ import annotations

import logging
import math
import warnings
from collections.abc import Callable
from itertools import product
from typing import Any

import pandas as pd

from quantflow.strategy.research.backtest import BacktestEngine

logger = logging.getLogger(__name__)


class StrategyOptimizer:
    """Optimize strategy parameters using Optuna or deterministic local sweeps."""

    def __init__(self, engine: BacktestEngine | None = None) -> None:
        self._engine = engine or BacktestEngine()

    def optimize(
        self,
        close: pd.Series,
        signal_fn: Callable[..., tuple[pd.Series, pd.Series]],
        param_space: dict[str, tuple[Any, ...]],
        n_trials: int = 200,
        method: str = "bayesian",
        initial_capital: float = 10000.0,
        fee: float = 0.001,
        objective: str = "sharpe",
    ) -> dict[str, Any]:
        """Run parameter optimization."""
        if method == "grid":
            return self._optimize_grid(
                close,
                signal_fn,
                param_space,
                n_trials=n_trials,
                initial_capital=initial_capital,
                fee=fee,
                objective=objective,
            )

        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)

        sampler = self._create_sampler(method)

        def optuna_objective(trial: optuna.Trial) -> float:
            params: dict[str, Any] = {}
            for name, spec in param_space.items():
                low, high = spec[0], spec[1]
                if isinstance(low, int) and isinstance(high, int):
                    params[name] = trial.suggest_int(name, low, high)
                else:
                    params[name] = trial.suggest_float(name, float(low), float(high))

            return self._evaluate_params(
                close,
                signal_fn,
                params,
                initial_capital=initial_capital,
                fee=fee,
                objective=objective,
                source="Optuna trial",
            )

        study = optuna.create_study(direction="maximize", sampler=sampler)
        study.optimize(optuna_objective, n_trials=n_trials, show_progress_bar=False)

        best = study.best_params
        best_value = study.best_value

        logger.info("Optimization complete: best_value=%.4f, params=%s", best_value, best)

        return {
            "best_params": best,
            "best_value": best_value,
            "n_trials": n_trials,
            "method": method,
            "objective": objective,
        }

    def _optimize_grid(
        self,
        close: pd.Series,
        signal_fn: Callable[..., tuple[pd.Series, pd.Series]],
        param_space: dict[str, tuple[Any, ...]],
        n_trials: int,
        initial_capital: float,
        fee: float,
        objective: str,
    ) -> dict[str, Any]:
        """Run deterministic local grid search without Optuna study overhead."""
        best_params: dict[str, Any] = {}
        best_value = -10.0
        evaluated = 0

        for params in self._grid_candidates(param_space, n_trials):
            value = self._evaluate_params(
                close,
                signal_fn,
                params,
                initial_capital=initial_capital,
                fee=fee,
                objective=objective,
                source="Grid trial",
            )
            evaluated += 1
            if value > best_value:
                best_value = value
                best_params = params

        logger.info(
            "Grid optimization complete: best_value=%.4f, params=%s", best_value, best_params
        )

        return {
            "best_params": best_params,
            "best_value": best_value,
            "n_trials": evaluated,
            "method": "grid",
            "objective": objective,
        }

    def _evaluate_params(
        self,
        close: pd.Series,
        signal_fn: Callable[..., tuple[pd.Series, pd.Series]],
        params: dict[str, Any],
        initial_capital: float,
        fee: float,
        objective: str,
        source: str,
    ) -> float:
        try:
            entries, exits = signal_fn(close, **params)
            result = self._engine.run_backtest(
                close,
                entries,
                exits,
                initial_capital=initial_capital,
                fee=fee,
            )
            value = self._objective_value(result, objective)
            if not math.isfinite(value):
                logger.warning("%s produced non-finite objective: %s", source, value)
                return -10.0
            return value
        except Exception as e:
            logger.warning("%s failed: %s", source, e)
            return -10.0

    @staticmethod
    def _objective_value(result: Any, objective: str) -> float:
        if objective == "sharpe":
            return float(result.sharpe_ratio)
        if objective == "sortino":
            return float(result.sortino_ratio)
        if objective == "calmar":
            return float(result.calmar_ratio)
        if objective == "return":
            return float(result.total_return)
        if objective == "win_rate":
            return float(result.win_rate)
        return float(result.sharpe_ratio)

    @staticmethod
    def _grid_candidates(
        param_space: dict[str, tuple[Any, ...]],
        n_trials: int,
    ) -> list[dict[str, Any]]:
        if n_trials < 1:
            return []
        if not param_space:
            return [{}]

        names = list(param_space)
        values = [StrategyOptimizer._grid_values(param_space[name], n_trials) for name in names]
        total_candidates = 1
        for grid_values in values:
            total_candidates *= len(grid_values)

        if total_candidates <= n_trials:
            return [dict(zip(names, combo, strict=True)) for combo in product(*values)]

        indexes = (
            [round(i * (total_candidates - 1) / (n_trials - 1)) for i in range(n_trials)]
            if n_trials > 1
            else [0]
        )

        candidates: list[dict[str, Any]] = []
        for index in indexes:
            combo: list[Any] = []
            remainder = index
            for grid_values in reversed(values):
                value_index = remainder % len(grid_values)
                combo.append(grid_values[value_index])
                remainder //= len(grid_values)
            combo.reverse()
            candidates.append(dict(zip(names, combo, strict=True)))
        return candidates

    @staticmethod
    def _grid_values(spec: tuple[Any, ...], n_trials: int) -> list[Any]:
        if not spec:
            return []
        if len(spec) == 1:
            return [spec[0]]
        # len > 2: treat as an explicit discrete candidate list (not a continuous range)
        if len(spec) > 2:
            return list(spec)[:n_trials]

        low, high = spec[0], spec[1]
        if isinstance(low, int) and isinstance(high, int):
            if n_trials == 1:
                return [low]
            span = high - low
            if span <= 0:
                return [low]
            int_step = max(1, round(span / max(n_trials - 1, 1)))
            values = list(range(low, high + 1, int_step))
            if values[-1] != high:
                values.append(high)
            return values[:n_trials]

        if n_trials == 1:
            return [float(low)]
        low_float = float(low)
        high_float = float(high)
        if low_float == high_float:
            return [low_float]
        float_step = (high_float - low_float) / (n_trials - 1)
        return [low_float + float_step * i for i in range(n_trials)]

    @staticmethod
    def _create_sampler(method: str) -> Any:
        import optuna

        if method == "cmaes":
            return optuna.samplers.CmaEsSampler()
        elif method == "grid":
            return (
                optuna.samplers.RandomSampler()
            )  # GridSampler requires search space; fallback to Random
        else:  # bayesian (default)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", optuna.exceptions.ExperimentalWarning)
                    return optuna.samplers.GPSampler()
            except (AttributeError, Exception):
                return optuna.samplers.TPESampler()
