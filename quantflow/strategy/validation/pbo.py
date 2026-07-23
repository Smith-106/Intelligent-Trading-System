"""PBO — Probability of Backtest Overfitting.

Quantifies the probability that a strategy's superior backtest performance
is due to overfitting rather than genuine alpha.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from quantflow.strategy.validation._common import sanitize_metric_array

logger = logging.getLogger(__name__)


def _sanitize_metric_array(values: list[float]) -> npt.NDArray[np.float64]:
    """Normalize validation metrics to finite floats (delegates to _common)."""
    return sanitize_metric_array(values)


def _pbo_failure_result(reason: str) -> dict[str, Any]:
    return {
        "pbo": 1.0,
        "overfit_paths": 0,
        "total_paths": 0,
        "is_return_mean": 0.0,
        "oos_return_mean": 0.0,
        "rank_correlation": 0.0,
        "passed": False,
        "reason": reason,
    }


def probability_of_overfitting(
    close: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
    n_groups: int = 8,
    n_test_groups: int = 2,
    embargo_pct: float = 0.01,
    initial_capital: float = 10000.0,
    fee: float = 0.001,
) -> dict[str, Any]:
    """Calculate PBO using the CPCV framework.

    PBO = fraction of paths where IS rank ≠ OOS rank (strategy is overfit).
    PBO < 0.5 means the strategy is likely NOT overfit.
    """
    from quantflow.strategy.research.backtest import BacktestEngine
    from quantflow.strategy.validation.cpcv import split_cpcv

    n_bars = len(close)
    try:
        splits = split_cpcv(n_bars, n_groups, n_test_groups, embargo_pct)
    except ValueError as exc:
        logger.warning("PBO skipped: %s", exc)
        return _pbo_failure_result(str(exc))
    engine = BacktestEngine()

    is_returns: list[float] = []
    oos_returns: list[float] = []

    for train_idx, test_idx in splits:
        try:
            is_res = engine.run_backtest(
                close.iloc[train_idx],
                entries.iloc[train_idx],
                exits.iloc[train_idx],
                initial_capital=initial_capital,
                fee=fee,
            )
            is_returns.append(is_res.total_return)
        except Exception:
            is_returns.append(0.0)

        try:
            oos_res = engine.run_backtest(
                close.iloc[test_idx],
                entries.iloc[test_idx],
                exits.iloc[test_idx],
                initial_capital=initial_capital,
                fee=fee,
            )
            oos_returns.append(oos_res.total_return)
        except Exception:
            oos_returns.append(0.0)

    is_returns_arr = _sanitize_metric_array(is_returns)
    oos_returns_arr = _sanitize_metric_array(oos_returns)

    # PBO: fraction of paths where IS is positive but OOS is negative
    is_positive = is_returns_arr > 0
    oos_negative = oos_returns_arr <= 0
    overfit_paths = np.sum(is_positive & oos_negative)
    total_paths = len(splits)

    pbo = overfit_paths / total_paths if total_paths > 0 else 1.0

    if len(is_returns_arr) > 1 and np.std(is_returns_arr) > 0 and np.std(oos_returns_arr) > 0:
        rank_correlation = float(
            pd.Series(is_returns_arr)
            .rank()
            .corr(pd.Series(oos_returns_arr).rank(), method="pearson")
        )
    else:
        rank_correlation = 0.0

    result = {
        "pbo": float(pbo),
        "overfit_paths": int(overfit_paths),
        "total_paths": total_paths,
        "is_return_mean": float(np.mean(is_returns_arr)),
        "oos_return_mean": float(np.mean(oos_returns_arr)),
        "rank_correlation": rank_correlation,
        "passed": pbo < 0.5,
    }

    logger.info(
        "PBO: %.3f (%d/%d overfit paths), rank_corr=%.3f, passed=%s",
        pbo,
        overfit_paths,
        total_paths,
        result["rank_correlation"],
        result["passed"],
    )
    return result
