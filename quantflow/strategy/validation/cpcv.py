"""CPCV — Combinatorial Purged Cross-Validation.

Implements the de Prado method for generating multiple backtest paths
with information leakage prevention via embargo periods.
"""

from __future__ import annotations

import logging
from itertools import combinations
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
    group_size = n_bars // n_groups
    groups = [np.arange(i * group_size, min((i + 1) * group_size, n_bars)) for i in range(n_groups)]
    # Handle remainder
    if groups[-1][-1] < n_bars - 1:
        groups[-1] = np.arange(groups[-1][0], n_bars)

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
) -> dict[str, Any]:
    """Run CPCV validation: backtest on all OOS paths.

    Returns dict with per-path results and aggregated PBO.
    """
    from quantflow.strategy.research.backtest import BacktestEngine

    n_bars = len(close)
    splits = split_cpcv(n_bars, n_groups, n_test_groups, embargo_pct)

    oos_sharpes: list[float] = []
    is_sharpes: list[float] = []
    path_results = []

    engine = BacktestEngine()

    for i, (train_idx, test_idx) in enumerate(splits):
        # In-sample backtest
        try:
            is_result = engine.run_backtest(
                close.iloc[train_idx],
                entries.iloc[train_idx],
                exits.iloc[train_idx],
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
                close.iloc[test_idx],
                entries.iloc[test_idx],
                exits.iloc[test_idx],
                initial_capital=initial_capital,
                fee=fee,
                strategy_id=f"cpcv_oos_{i}",
            )
            oos_sharpes.append(oos_result.sharpe_ratio)
            path_results.append(
                {
                    "path": i,
                    "oos_sharpe": oos_result.sharpe_ratio,
                    "oos_return": oos_result.total_return,
                    "oos_max_dd": oos_result.max_drawdown,
                    "oos_trades": oos_result.num_trades,
                }
            )
        except Exception:
            oos_sharpes.append(0.0)
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
