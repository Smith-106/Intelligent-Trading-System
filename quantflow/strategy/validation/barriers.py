"""Triple-Barrier Method for labeling price paths.

Based on Lopez de Prado's method: label observations based on
which barrier is hit first (profit-taking, stop-loss, or time).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def triple_barrier_labels(
    close: pd.Series,
    profit_take_pct: float = 0.02,
    stop_loss_pct: float = 0.02,
    max_holding: int = 20,
) -> pd.DataFrame:
    """Generate triple-barrier labels for price series.

    Returns DataFrame with columns:
    - label: 1 (profit hit first), -1 (stop hit first), 0 (time barrier)
    - barrier_hit: which barrier was touched first
    - holding_period: number of bars until barrier hit
    """
    labels = []
    n = len(close)

    for i in range(n):
        entry_price = close.iloc[i]
        profit_target = entry_price * (1 + profit_take_pct)
        stop_target = entry_price * (1 - stop_loss_pct)
        end_bar = min(i + max_holding, n)

        label = 0
        barrier = "time"
        hold = end_bar - i

        for j in range(i + 1, end_bar):
            price = close.iloc[j]
            if price >= profit_target:
                label = 1
                barrier = "profit"
                hold = j - i
                break
            elif price <= stop_target:
                label = -1
                barrier = "stop"
                hold = j - i
                break

        labels.append({
            "label": label,
            "barrier_hit": barrier,
            "holding_period": hold,
        })

    return pd.DataFrame(labels, index=close.index)


def minimum_track_record_length(
    sharpe: float,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Calculate minimum track record length to validate a Sharpe ratio.

    How many observations are needed to have confidence that the
    observed Sharpe ratio is genuinely positive?
    """
    from scipy import stats

    if sharpe <= 0:
        return {"min_trl": float("inf"), "passed": False, "reason": "non_positive_sharpe"}

    # MinTRL ≈ (Z_alpha / SR)^2 * (1 - skew*SR + (kurtosis-1)/4*SR^2)
    z_alpha = stats.norm.ppf(confidence)
    adj_factor = 1 - skew * sharpe + (kurtosis - 1) / 4 * sharpe ** 2
    min_trl = (z_alpha / sharpe) ** 2 * max(adj_factor, 1.0)

    return {
        "min_trl": int(np.ceil(min_trl)),
        "sharpe": sharpe,
        "confidence": confidence,
        "adjusted_factor": adj_factor,
    }
