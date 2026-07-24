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
            # ISS-030: NaN sentinel for failed paths (excluded from PBO via the
            # finite mask). The prior 0.0 made is_positive=False, so a path that
            # genuinely overfit (real IS>0, real OOS<0) but whose IS backtest
            # THREW was silently counted as not-overfit, lowering the PBO and
            # passing bad strategies.
            is_returns.append(float("nan"))

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
            oos_returns.append(float("nan"))

    is_raw = np.asarray(is_returns, dtype=float)
    oos_raw = np.asarray(oos_returns, dtype=float)
    finite = np.isfinite(is_raw) & np.isfinite(oos_raw)
    n_valid_paths = int(finite.sum())

    # PBO: fraction of FINITE paths where IS is positive but OOS is negative.
    # No finite paths → fail-closed pbo=1.0 (forces NO-GO) rather than 0.0.
    if n_valid_paths > 0:
        is_positive = is_raw[finite] > 0
        oos_negative = oos_raw[finite] <= 0
        overfit_paths = int(np.sum(is_positive & oos_negative))
        pbo = overfit_paths / n_valid_paths
    else:
        overfit_paths = 0
        pbo = 1.0
    total_paths = len(splits)

    if n_valid_paths > 1 and np.nanstd(is_raw) > 0 and np.nanstd(oos_raw) > 0:
        rank_correlation = float(
            pd.Series(is_raw[finite])
            .rank()
            .corr(pd.Series(oos_raw[finite]).rank(), method="pearson")
        )
    else:
        rank_correlation = 0.0

    result = {
        "pbo": float(pbo),
        "overfit_paths": overfit_paths,
        "total_paths": total_paths,
        "n_valid_paths": n_valid_paths,
        "is_return_mean": float(np.nanmean(is_raw)) if n_valid_paths > 0 else 0.0,
        "oos_return_mean": float(np.nanmean(oos_raw)) if n_valid_paths > 0 else 0.0,
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
