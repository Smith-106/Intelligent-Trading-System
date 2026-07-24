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
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from quantflow.strategy.validation._common import sanitize_metric_array
from quantflow.strategy.validation.signal_quality import (
    aggregate_signal_quality,
    signal_quality_metrics,
)

logger = logging.getLogger(__name__)

SignalFunction = Callable[..., tuple[pd.Series, pd.Series]]


def _sanitize_metric_array(values: list[float]) -> npt.NDArray[np.float64]:
    """Normalize validation metrics to finite floats (delegates to _common)."""
    return sanitize_metric_array(values)


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
        skipped_folds = 0
        for i in range(self.n_folds):
            # Train/test boundaries
            test_start = (i + 1) * fold_size
            test_end = min(test_start + test_size, n)

            train_start = 0 if self.anchored else i * fold_size

            train_end = test_start - self.purge_delta

            if train_end <= train_start or test_end <= test_start:
                # ISS-028: a skipped fold previously reduced the effective fold
                # count silently — n_folds configured vs actual could diverge
                # with no signal. Count and warn so an operator sees the gap.
                skipped_folds += 1
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
            if skipped_folds:
                logger.warning(
                    "WFO: all %d folds skipped (train_end<=train_start or "
                    "test_end<=test_start) — data too short for n_folds=%d",
                    skipped_folds,
                    self.n_folds,
                )
            return WFOResult(
                folds=[],
                mean_train_sharpe=0.0,
                mean_test_sharpe=0.0,
                test_sharpe_std=0.0,
                degradation=0.0,
                passed=False,
                degradation_threshold=self.degradation_threshold,
                total_test_return=0.0,
                details={
                    "error": "no valid folds produced",
                    "skipped_folds": skipped_folds,
                    "configured_n_folds": self.n_folds,
                },
            )

        if skipped_folds:
            logger.warning(
                "WFO: %d of %d folds skipped — effective fold count is %d",
                skipped_folds,
                self.n_folds,
                len(folds),
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
            details={
                "skipped_folds": skipped_folds,
                "configured_n_folds": self.n_folds,
                "effective_n_folds": len(folds),
            },
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
    signal_fn: SignalFunction | None = None,
    param_space: dict[str, tuple[Any, ...]] | None = None,
    data: pd.DataFrame | None = None,
    n_trials: int = 50,
    method: str = "bayesian",
    objective: str = "sharpe",
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
        signal_fn: Optional callable(frame, **params) -> (entries, exits). When
            supplied with param_space, every train window is optimized and the
            selected params are applied to the OOS window.
        param_space: Parameter search space for train-window optimization.
        data: Full OHLCV frame used by signal_fn. Defaults to a close-only frame.
        n_trials: Number of optimization trials per WFO window.
        method: Optimizer sampler method.
        objective: Optimization objective.

    Returns:
        Dict with aggregated results and GO/NO-GO decision.
    """
    from quantflow.strategy.research.backtest import BacktestEngine
    from quantflow.strategy.research.optimizer import StrategyOptimizer

    n_bars = len(close)
    if n_windows < 1:
        raise ValueError("n_windows must be >= 1")

    window_size = max(n_bars // n_windows, 1)
    oos_size = int(window_size * oos_ratio)

    engine = BacktestEngine()
    window_results = []
    all_oos_sharpes: list[float] = []
    all_is_sharpes: list[float] = []
    quality_rows: list[dict[str, Any]] = []
    source_data = (
        data.copy() if data is not None else pd.DataFrame({"close": close}, index=close.index)
    )
    uses_oos_signal_generation = signal_fn is not None
    optimized = signal_fn is not None and param_space is not None

    for i in range(n_windows):
        is_start = 0 if mode == "anchored" else i * window_size
        is_end = (i + 1) * window_size - oos_size
        oos_start = is_end
        oos_end = (i + 1) * window_size

        is_idx = np.arange(max(is_start, 0), min(is_end, n_bars))
        oos_idx = np.arange(max(oos_start, 0), min(oos_end, n_bars))
        train_frame = source_data.iloc[is_idx].copy()
        oos_frame = source_data.iloc[oos_idx].copy()
        train_close = close.iloc[is_idx]
        oos_close = close.iloc[oos_idx]
        best_params: dict[str, Any] = {}

        if signal_fn is not None and param_space is not None:
            optimized_signal_fn = signal_fn
            optimized_param_space = param_space
            optimizer = StrategyOptimizer(engine=engine)

            def _train_signal_fn(
                train_close_slice: pd.Series,
                train_data: pd.DataFrame = train_frame,
                train_signal_fn: SignalFunction = optimized_signal_fn,
                **params: Any,
            ) -> tuple[pd.Series, pd.Series]:
                train_slice = train_data.copy()
                if "close" in train_slice.columns:
                    train_slice["close"] = train_close_slice.to_numpy()
                generated_entries, generated_exits = train_signal_fn(train_slice, **params)
                return (
                    generated_entries.reindex(train_slice.index).fillna(False).astype(bool),
                    generated_exits.reindex(train_slice.index).fillna(False).astype(bool),
                )

            try:
                optimization = optimizer.optimize(
                    train_close,
                    _train_signal_fn,
                    optimized_param_space,
                    n_trials=n_trials,
                    method=method,
                    initial_capital=initial_capital,
                    fee=fee,
                    objective=objective,
                )
                best_params = dict(optimization.get("best_params", {}))
            except Exception as exc:
                logger.warning("WFO window %d train optimization failed: %s", i, exc)
                best_params = {}

        if signal_fn is not None:
            try:
                train_entries, train_exits = signal_fn(train_frame, **best_params)
                train_entries = train_entries.reindex(train_frame.index).fillna(False).astype(bool)
                train_exits = train_exits.reindex(train_frame.index).fillna(False).astype(bool)
            except Exception as exc:
                logger.warning("WFO window %d train signal generation failed: %s", i, exc)
                train_entries = pd.Series(False, index=train_frame.index)
                train_exits = pd.Series(False, index=train_frame.index)
            try:
                oos_entries, oos_exits = signal_fn(oos_frame, **best_params)
                oos_entries = oos_entries.reindex(oos_frame.index).fillna(False).astype(bool)
                oos_exits = oos_exits.reindex(oos_frame.index).fillna(False).astype(bool)
            except Exception as exc:
                logger.warning("WFO window %d OOS signal generation failed: %s", i, exc)
                oos_entries = pd.Series(False, index=oos_frame.index)
                oos_exits = pd.Series(False, index=oos_frame.index)
        else:
            train_entries = entries.iloc[is_idx]
            train_exits = exits.iloc[is_idx]
            oos_entries = entries.iloc[oos_idx]
            oos_exits = exits.iloc[oos_idx]

        try:
            is_res = engine.run_backtest(
                train_close,
                train_entries,
                train_exits,
                initial_capital=initial_capital,
                fee=fee,
            )
            is_sharpe = is_res.sharpe_ratio
        except Exception:
            is_sharpe = 0.0

        try:
            oos_res = engine.run_backtest(
                oos_close,
                oos_entries,
                oos_exits,
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

        signal_quality = signal_quality_metrics(
            oos_close,
            oos_entries,
            oos_exits,
            oos_sharpe=oos_sharpe,
        )
        quality_rows.append(signal_quality)
        all_is_sharpes.append(is_sharpe)
        all_oos_sharpes.append(oos_sharpe)
        window_results.append(
            {
                "window": i,
                "is_start": int(is_start),
                "is_end": int(is_end),
                "oos_start": int(oos_start),
                "oos_end": int(oos_end),
                "is_sharpe": is_sharpe,
                "oos_sharpe": oos_sharpe,
                "oos_return": oos_return,
                "oos_max_dd": oos_max_dd,
                "oos_trades": oos_trades,
                "best_params": best_params,
                "optimized": optimized,
                "oos_recomputed": uses_oos_signal_generation,
                "signal_quality": signal_quality,
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
        "optimized": optimized,
        "oos_recomputed": uses_oos_signal_generation,
        "signal_quality": aggregate_signal_quality(quality_rows),
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
