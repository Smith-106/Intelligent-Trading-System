"""Walk-Forward Optimization (WFO).

Validates strategy by repeatedly optimizing on a training window and testing
on the subsequent out-of-sample window. This simulates how a strategy would
perform in live trading when parameters are periodically re-optimized.

Reference: Robert Pardo (2008), "The Evaluation and Optimization of Trading Strategies".
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

import numpy as np
import numpy.typing as npt
import pandas as pd

logger = logging.getLogger(__name__)


def _sanitize_metric_array(values: list[float]) -> npt.NDArray[np.float64]:
    """Normalize validation metrics to finite floats to avoid numeric warnings."""
    arr = np.asarray(values, dtype=float)
    sanitized = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    return cast(npt.NDArray[np.float64], sanitized.astype(np.float64, copy=False))


@dataclass
class WFOFoldResult:
    """Result from a single WFO fold."""

    fold_index: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    train_sharpe: float
    test_sharpe: float
    train_return: float
    test_return: float
    best_params: dict[str, Any]


@dataclass
class WFOResult:
    """Aggregated result from Walk-Forward Optimization."""

    folds: list[WFOFoldResult]
    mean_train_sharpe: float
    mean_test_sharpe: float
    test_sharpe_std: float
    degradation: float  # test_sharpe / train_sharpe
    passed: bool
    degradation_threshold: float
    total_test_return: float
    details: dict[str, Any] = field(default_factory=dict)


class WalkForwardOptimization:
    """Walk-Forward Optimization with anchored or rolling windows.

    Splits data into sequential folds, optimizes parameters on each
    training window, and evaluates on the following test window.
    """

    def __init__(
        self,
        n_folds: int = 5,
        test_ratio: float = 0.2,
        anchored: bool = False,
        degradation_threshold: float = 0.5,
        purge_delta: int = 5,
    ):
        self.n_folds = n_folds
        self.test_ratio = test_ratio
        self.anchored = anchored
        self.degradation_threshold = degradation_threshold
        self.purge_delta = purge_delta

    def run(
        self,
        close: pd.Series,
        entries: pd.Series,
        exits: pd.Series,
        optimize_fn: Callable[[pd.Series], tuple[pd.Series, pd.Series, dict[str, Any]]]
        | None = None,
    ) -> WFOResult:
        """Run walk-forward validation.

        Args:
            close: Price series.
            entries: Boolean entry signals.
            exits: Boolean exit signals.
            optimize_fn: Optional callable(train_close) -> (entries, exits, params).
                         If None, uses the provided signals directly.

        Returns:
            WFOResult with performance across all folds.
        """
        n = len(close)
        fold_size = n // self.n_folds
        test_size = int(fold_size * self.test_ratio)

        folds = []
        for i in range(self.n_folds):
            # Train/test boundaries
            test_start = (i + 1) * fold_size
            test_end = min(test_start + test_size, n)

            train_start = 0 if self.anchored else i * fold_size

            train_end = test_start - self.purge_delta

            if train_end <= train_start or test_end <= test_start:
                continue

            # Get train/test data
            train_close = close.iloc[train_start:train_end]
            test_close = close.iloc[test_start:test_end]

            if optimize_fn is not None:
                train_entries, train_exits, best_params = optimize_fn(train_close)
            else:
                train_entries = entries.iloc[train_start:train_end]
                train_exits = exits.iloc[train_start:train_end]
                best_params = {}

            # Evaluate on training set
            train_sharpe = self._compute_sharpe(train_close, train_entries, train_exits)
            train_return = self._compute_return(train_close, train_entries, train_exits)

            # Evaluate on test set
            test_entries = entries.iloc[test_start:test_end]
            test_exits = exits.iloc[test_start:test_end]
            test_sharpe = self._compute_sharpe(test_close, test_entries, test_exits)
            test_return = self._compute_return(test_close, test_entries, test_exits)

            folds.append(
                WFOFoldResult(
                    fold_index=i,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    train_sharpe=train_sharpe,
                    test_sharpe=test_sharpe,
                    train_return=train_return,
                    test_return=test_return,
                    best_params=best_params,
                )
            )

        if not folds:
            return WFOResult(
                folds=[],
                mean_train_sharpe=0.0,
                mean_test_sharpe=0.0,
                test_sharpe_std=0.0,
                degradation=0.0,
                passed=False,
                degradation_threshold=self.degradation_threshold,
                total_test_return=0.0,
                details={"error": "no valid folds produced"},
            )

        train_sharpes = [f.train_sharpe for f in folds]
        test_sharpes = [f.test_sharpe for f in folds]
        test_returns = [f.test_return for f in folds]

        mean_train = float(np.mean(train_sharpes))
        mean_test = float(np.mean(test_sharpes))
        std_test = float(np.std(test_sharpes)) if len(test_sharpes) > 1 else 0.0

        degradation = mean_test / mean_train if abs(mean_train) > 1e-10 else 0.0
        total_test_return = float(sum(test_returns))

        passed = degradation >= self.degradation_threshold

        return WFOResult(
            folds=folds,
            mean_train_sharpe=mean_train,
            mean_test_sharpe=mean_test,
            test_sharpe_std=std_test,
            degradation=degradation,
            passed=passed,
            degradation_threshold=self.degradation_threshold,
            total_test_return=total_test_return,
        )

    @staticmethod
    def _compute_sharpe(
        close: pd.Series,
        entries: pd.Series,
        exits: pd.Series,
    ) -> float:
        """Compute Sharpe ratio for a price/signals segment."""
        in_position = False
        entry_price = 0.0
        returns = []

        for i in range(1, len(close)):
            if not in_position and entries.iloc[i - 1]:
                in_position = True
                entry_price = close.iloc[i]
            elif in_position and exits.iloc[i - 1]:
                exit_price = close.iloc[i]
                ret = (exit_price - entry_price) / entry_price
                returns.append(ret)
                in_position = False

        if not returns:
            return 0.0
        r = np.array(returns)
        if r.std() == 0:
            return 0.0
        return float(r.mean() / r.std() * np.sqrt(252))

    @staticmethod
    def _compute_return(
        close: pd.Series,
        entries: pd.Series,
        exits: pd.Series,
    ) -> float:
        """Compute total return for a price/signals segment."""
        in_position = False
        entry_price = 0.0
        total_ret = 0.0

        for i in range(1, len(close)):
            if not in_position and entries.iloc[i - 1]:
                in_position = True
                entry_price = close.iloc[i]
            elif in_position and exits.iloc[i - 1]:
                exit_price = close.iloc[i]
                total_ret += (exit_price - entry_price) / entry_price
                in_position = False

        return total_ret


def walk_forward_optimization(
    close: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
    n_windows: int = 5,
    mode: str = "rolling",
    oos_ratio: float = 0.3,
    initial_capital: float = 10000.0,
    fee: float = 0.001,
) -> dict[str, Any]:
    """Backward-compatible function interface for Walk-Forward Optimization.

    Args:
        close: Price series.
        entries: Entry signals.
        exits: Exit signals.
        n_windows: Number of walk-forward windows.
        mode: 'rolling' or 'anchored'.
        oos_ratio: Fraction of each window for OOS testing.
        initial_capital: Starting capital.
        fee: Trading fee rate.

    Returns:
        Dict with aggregated results and GO/NO-GO decision.
    """
    from quantflow.strategy.research.backtest import BacktestEngine

    n_bars = len(close)
    window_size = n_bars // n_windows
    oos_size = int(window_size * oos_ratio)

    engine = BacktestEngine()
    window_results = []
    all_oos_sharpes: list[float] = []
    all_is_sharpes: list[float] = []

    for i in range(n_windows):
        is_start = 0 if mode == "anchored" else i * window_size
        is_end = (i + 1) * window_size - oos_size
        oos_start = is_end
        oos_end = (i + 1) * window_size

        if oos_end > n_bars:
            break

        is_idx = np.arange(is_start, is_end)
        oos_idx = np.arange(oos_start, oos_end)

        try:
            is_res = engine.run_backtest(
                close.iloc[is_idx],
                entries.iloc[is_idx],
                exits.iloc[is_idx],
                initial_capital=initial_capital,
                fee=fee,
            )
            is_sharpe = is_res.sharpe_ratio
        except Exception:
            is_sharpe = 0.0

        try:
            oos_res = engine.run_backtest(
                close.iloc[oos_idx],
                entries.iloc[oos_idx],
                exits.iloc[oos_idx],
                initial_capital=initial_capital,
                fee=fee,
            )
            oos_sharpe = oos_res.sharpe_ratio
            oos_return = oos_res.total_return
            oos_max_dd = oos_res.max_drawdown
            oos_trades = oos_res.num_trades
        except Exception:
            oos_sharpe = 0.0
            oos_return = 0.0
            oos_max_dd = 0.0
            oos_trades = 0

        all_is_sharpes.append(is_sharpe)
        all_oos_sharpes.append(oos_sharpe)
        window_results.append(
            {
                "window": i,
                "is_sharpe": is_sharpe,
                "oos_sharpe": oos_sharpe,
                "oos_return": oos_return,
                "oos_max_dd": oos_max_dd,
                "oos_trades": oos_trades,
            }
        )

    all_is_sharpes_arr = _sanitize_metric_array(all_is_sharpes)
    all_oos_sharpes_arr = _sanitize_metric_array(all_oos_sharpes)

    is_mean = float(np.mean(all_is_sharpes_arr))
    oos_mean = float(np.mean(all_oos_sharpes_arr))
    oos_efficiency = oos_mean / max(is_mean, 1e-6)

    go_threshold = 0.5
    decision = "GO" if oos_efficiency > go_threshold else "NO-GO"

    result = {
        "mode": mode,
        "n_windows": len(window_results),
        "oos_ratio": oos_ratio,
        "is_sharpe_mean": is_mean,
        "oos_sharpe_mean": oos_mean,
        "oos_efficiency": oos_efficiency,
        "oos_efficiency_threshold": go_threshold,
        "decision": decision,
        "window_results": window_results,
        "passed": decision == "GO",
    }

    logger.info(
        "WFO(%s): OOS eff=%.3f, IS=%.3f, OOS=%.3f, decision=%s",
        mode,
        oos_efficiency,
        is_mean,
        oos_mean,
        decision,
    )
    return result
