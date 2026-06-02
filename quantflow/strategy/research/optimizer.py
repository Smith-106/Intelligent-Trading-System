"""Optuna-based parameter optimization."""

from __future__ import annotations

import logging
import warnings
from collections.abc import Callable
from typing import Any

import pandas as pd

from quantflow.strategy.research.backtest import BacktestEngine

logger = logging.getLogger(__name__)


class StrategyOptimizer:
    """Optimize strategy parameters using Optuna."""

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

            try:
                entries, exits = signal_fn(close, **params)
                result = self._engine.run_backtest(
                    close,
                    entries,
                    exits,
                    initial_capital=initial_capital,
                    fee=fee,
                )
                if objective == "sharpe":
                    return result.sharpe_ratio
                elif objective == "sortino":
                    return result.sortino_ratio
                elif objective == "calmar":
                    return result.calmar_ratio
                elif objective == "return":
                    return result.total_return
                else:
                    return result.sharpe_ratio
            except Exception as e:
                logger.warning("Optuna trial failed: %s", e)
                return -10.0

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
