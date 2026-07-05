"""CPCV — Combinatorial Purged Cross-Validation.

Implements the de Prado method for generating multiple backtest paths
with information leakage prevention via embargo periods.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from itertools import combinations
from typing import Any, cast

import numpy as np
import numpy.typing as npt
import pandas as pd

from quantflow.strategy.validation.signal_quality import (
    aggregate_signal_quality,
    signal_quality_metrics,
)

logger = logging.getLogger(__name__)
SignalFunction = Callable[..., tuple[pd.Series, pd.Series]]


def _sanitize_metric_array(values: list[float]) -> npt.NDArray[np.float64]:
    """Normalize validation metrics to finite floats to avoid numeric warnings."""
    arr = np.asarray(values, dtype=float)
    sanitized = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    return cast(npt.NDArray[np.float64], sanitized.astype(np.float64, copy=False))


def _cpcv_failure_result(
    reason: str,
    *,
    optimized: bool = False,
    oos_recomputed: bool = False,
) -> dict[str, Any]:
    return {
        "n_paths": 0,
        "pbo": 1.0,
        "oos_efficiency": 0.0,
        "is_sharpe_mean": 0.0,
        "is_sharpe_std": 0.0,
        "oos_sharpe_mean": 0.0,
        "oos_sharpe_std": 0.0,
        "oos_sharpe_min": 0.0,
        "path_results": [],
        "optimized": optimized,
        "oos_recomputed": oos_recomputed,
        "signal_quality": aggregate_signal_quality([]),
        "passed": False,
        "reason": reason,
    }


def split_cpcv(
    n_bars: int,
    n_groups: int = 8,
    n_test_groups: int = 2,
    embargo_pct: float = 0.01,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Generate CPCV train/test index splits.

    Returns list of (train_indices, test_indices) for each combination
    of test groups. With n_groups=8, n_test_groups=2 → C(8,2)=28 paths.
    """
    if n_bars < 2:
        raise ValueError("CPCV requires at least 2 bars.")
    if n_groups < 2:
        raise ValueError("CPCV requires at least 2 groups.")
    if n_test_groups < 1:
        raise ValueError("CPCV requires at least 1 test group.")
    if n_test_groups >= n_groups:
        raise ValueError("CPCV test groups must be fewer than total groups.")
    if n_bars < n_groups:
        raise ValueError(f"CPCV requires at least {n_groups} bars, got {n_bars}.")

    group_size = n_bars // n_groups
    if (
        group_size <= 0
    ):  # pragma: no cover — unreachable: n_bars >= n_groups guarantees group_size >= 1
        raise ValueError(
            f"CPCV group size collapsed to 0 for {n_bars} bars across {n_groups} groups."
        )
    # Distribute bars as evenly as possible so group sizes differ by at most 1.
    # Dumping all remainder bars into the last group biased OOS test sizes
    # (the last group could be much larger than the others).
    groups = [arr for arr in np.array_split(np.arange(n_bars), n_groups)]

    embargo_bars = max(1, int(n_bars * embargo_pct))
    splits = []

    for test_combo in combinations(range(n_groups), n_test_groups):
        test_idx = np.concatenate([groups[i] for i in test_combo])
        train_idx = np.concatenate([groups[i] for i in range(n_groups) if i not in test_combo])

        # Apply embargo: remove train samples within embargo distance of test
        embargo_mask = np.zeros(len(train_idx), dtype=bool)
        for t in test_idx:
            embargo_mask |= np.abs(train_idx - t) <= embargo_bars
        train_idx = train_idx[~embargo_mask]

        splits.append((train_idx, test_idx))

    logger.info(
        "CPCV: %d groups × %d test = %d paths (embargo=%d bars)",
        n_groups,
        n_test_groups,
        len(splits),
        embargo_bars,
    )
    return splits


def cpcv_backtest(
    close: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
    n_groups: int = 8,
    n_test_groups: int = 2,
    embargo_pct: float = 0.01,
    initial_capital: float = 10000.0,
    fee: float = 0.001,
    signal_fn: SignalFunction | None = None,
    param_space: dict[str, tuple[Any, ...]] | None = None,
    data: pd.DataFrame | None = None,
    n_trials: int = 50,
    method: str = "bayesian",
    objective: str = "sharpe",
) -> dict[str, Any]:
    """Run CPCV validation: backtest on all OOS paths.

    Returns dict with per-path results and aggregated PBO.
    """
    from quantflow.strategy.research.backtest import BacktestEngine
    from quantflow.strategy.research.optimizer import StrategyOptimizer

    n_bars = len(close)
    optimized = signal_fn is not None and param_space is not None
    try:
        splits = split_cpcv(n_bars, n_groups, n_test_groups, embargo_pct)
    except ValueError as exc:
        logger.warning("CPCV skipped: %s", exc)
        return _cpcv_failure_result(
            str(exc),
            optimized=optimized,
            oos_recomputed=signal_fn is not None,
        )

    oos_sharpes: list[float] = []
    is_sharpes: list[float] = []
    path_results = []
    quality_rows: list[dict[str, Any]] = []

    engine = BacktestEngine()
    source_data = (
        data.copy() if data is not None else pd.DataFrame({"close": close}, index=close.index)
    )
    uses_oos_signal_generation = signal_fn is not None

    for i, (train_idx, test_idx) in enumerate(splits):
        train_close = close.iloc[train_idx]
        test_close = close.iloc[test_idx]
        train_frame = source_data.iloc[train_idx].copy()
        test_frame = source_data.iloc[test_idx].copy()
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
                logger.warning("CPCV path %d train optimization failed: %s", i, exc)
                best_params = {}

        if signal_fn is not None:
            try:
                train_entries, train_exits = signal_fn(train_frame, **best_params)
                train_entries = train_entries.reindex(train_frame.index).fillna(False).astype(bool)
                train_exits = train_exits.reindex(train_frame.index).fillna(False).astype(bool)
            except Exception as exc:
                logger.warning("CPCV path %d train signal generation failed: %s", i, exc)
                train_entries = pd.Series(False, index=train_frame.index)
                train_exits = pd.Series(False, index=train_frame.index)
            try:
                test_entries, test_exits = signal_fn(test_frame, **best_params)
                test_entries = test_entries.reindex(test_frame.index).fillna(False).astype(bool)
                test_exits = test_exits.reindex(test_frame.index).fillna(False).astype(bool)
            except Exception as exc:
                logger.warning("CPCV path %d OOS signal generation failed: %s", i, exc)
                test_entries = pd.Series(False, index=test_frame.index)
                test_exits = pd.Series(False, index=test_frame.index)
        else:
            train_entries = entries.iloc[train_idx]
            train_exits = exits.iloc[train_idx]
            test_entries = entries.iloc[test_idx]
            test_exits = exits.iloc[test_idx]

        # In-sample backtest
        try:
            is_result = engine.run_backtest(
                train_close,
                train_entries,
                train_exits,
                initial_capital=initial_capital,
                fee=fee,
                strategy_id=f"cpcv_is_{i}",
            )
            is_sharpes.append(is_result.sharpe_ratio)
        except Exception:
            is_sharpes.append(0.0)

        # Out-of-sample backtest
        try:
            oos_result = engine.run_backtest(
                test_close,
                test_entries,
                test_exits,
                initial_capital=initial_capital,
                fee=fee,
                strategy_id=f"cpcv_oos_{i}",
            )
            oos_sharpes.append(oos_result.sharpe_ratio)
            signal_quality = signal_quality_metrics(
                test_close,
                test_entries,
                test_exits,
                oos_sharpe=oos_result.sharpe_ratio,
            )
            quality_rows.append(signal_quality)
            path_results.append(
                {
                    "path": i,
                    "oos_sharpe": oos_result.sharpe_ratio,
                    "oos_return": oos_result.total_return,
                    "oos_max_dd": oos_result.max_drawdown,
                    "oos_trades": oos_result.num_trades,
                    "best_params": best_params,
                    "optimized": optimized,
                    "oos_recomputed": uses_oos_signal_generation,
                    "signal_quality": signal_quality,
                }
            )
        except Exception:
            oos_sharpes.append(0.0)
            signal_quality = signal_quality_metrics(
                test_close, test_entries, test_exits, oos_sharpe=0.0
            )
            quality_rows.append(signal_quality)
            if uses_oos_signal_generation:
                path_results.append(
                    {
                        "path": i,
                        "oos_sharpe": 0.0,
                        "best_params": best_params,
                        "optimized": optimized,
                        "oos_recomputed": True,
                        "signal_quality": signal_quality,
                    }
                )
            else:
                path_results.append({"path": i, "oos_sharpe": 0.0})

    is_sharpes_arr = _sanitize_metric_array(is_sharpes)
    oos_sharpes_arr = _sanitize_metric_array(oos_sharpes)

    # PBO: fraction of paths where IS > OOS (overfitting indicator)
    pbo = float(np.mean(is_sharpes_arr > oos_sharpes_arr))

    # OOS efficiency
    oos_efficiency = float(np.mean(oos_sharpes_arr) / max(float(np.mean(is_sharpes_arr)), 1e-6))

    result = {
        "n_paths": len(splits),
        "pbo": pbo,
        "oos_efficiency": oos_efficiency,
        "is_sharpe_mean": float(np.mean(is_sharpes_arr)),
        "is_sharpe_std": float(np.std(is_sharpes_arr)),
        "oos_sharpe_mean": float(np.mean(oos_sharpes_arr)),
        "oos_sharpe_std": float(np.std(oos_sharpes_arr)),
        "oos_sharpe_min": float(np.min(oos_sharpes_arr)),
        "path_results": path_results,
        "optimized": optimized,
        "oos_recomputed": uses_oos_signal_generation,
        "signal_quality": aggregate_signal_quality(quality_rows),
        "passed": pbo < 0.5,
    }

    logger.info(
        "CPCV result: PBO=%.3f, OOS eff=%.3f, OOS Sharpe mean=%.3f±%.3f, passed=%s",
        pbo,
        oos_efficiency,
        result["oos_sharpe_mean"],
        result["oos_sharpe_std"],
        result["passed"],
    )
    return result
