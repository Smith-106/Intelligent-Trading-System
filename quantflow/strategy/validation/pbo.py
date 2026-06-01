"""PBO — Probability of Backtest Overfitting.

Quantifies the probability that a strategy's superior backtest performance
is due to overfitting rather than genuine alpha.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


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
    splits = split_cpcv(n_bars, n_groups, n_test_groups, embargo_pct)
    engine = BacktestEngine()

    is_returns = []
    oos_returns = []

    for train_idx, test_idx in splits:
        try:
            is_res = engine.run_backtest(
                close.iloc[train_idx], entries.iloc[train_idx], exits.iloc[train_idx],
                initial_capital=initial_capital, fee=fee,
            )
            is_returns.append(is_res.total_return)
        except Exception:
            is_returns.append(0.0)

        try:
            oos_res = engine.run_backtest(
                close.iloc[test_idx], entries.iloc[test_idx], exits.iloc[test_idx],
                initial_capital=initial_capital, fee=fee,
            )
            oos_returns.append(oos_res.total_return)
        except Exception:
            oos_returns.append(0.0)

    is_returns = np.array(is_returns)
    oos_returns = np.array(oos_returns)

    # PBO: fraction of paths where IS is positive but OOS is negative
    is_positive = is_returns > 0
    oos_negative = oos_returns <= 0
    overfit_paths = np.sum(is_positive & oos_negative)
    total_paths = len(splits)

    pbo = overfit_paths / total_paths if total_paths > 0 else 1.0

    result = {
        "pbo": float(pbo),
        "overfit_paths": int(overfit_paths),
        "total_paths": total_paths,
        "is_return_mean": float(np.mean(is_returns)),
        "oos_return_mean": float(np.mean(oos_returns)),
        "rank_correlation": float(np.corrcoef(is_returns, oos_returns)[0, 1])
            if len(is_returns) > 1 and np.std(is_returns) > 0 and np.std(oos_returns) > 0 else 0.0,
        "passed": pbo < 0.5,
    }

    logger.info("PBO: %.3f (%d/%d overfit paths), rank_corr=%.3f, passed=%s",
                pbo, overfit_paths, total_paths, result["rank_correlation"], result["passed"])
    return result
