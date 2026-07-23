"""DSR — Deflated Sharpe Ratio.

Corrects for multiple testing bias when selecting the best strategy
from many backtests. Based on Bailey & Lopez de Prado (2014).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_trials: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    sample_length: int = 252,
    annualize_factor: int = 252,
) -> dict[str, Any]:
    """Calculate the Deflated Sharpe Ratio.

    Args:
        observed_sharpe: The best observed Sharpe ratio from N trials.
        n_trials: Number of independent backtests run.
        skew: Skewness of returns distribution.
        kurtosis: Excess kurtosis of returns distribution.
        sample_length: Number of observations in the backtest.
        annualize_factor: Annualization factor (252 for daily).

    Returns:
        Dict with DSR value and interpretation.
    """
    if n_trials < 1:
        return {"dsr": 0.0, "passed": False, "reason": "no_trials"}

    # Expected Sharpe under null (random)
    # E[max(SR)] ≈ (1-γ)·Z^{-1}(1-1/N) + γ·Z^{-1}(1-1/(N·e))
    # Simplified: use the expected maximum of N standard normals
    expected_max_sr = _expected_max_sharpe(n_trials)

    # Adjust for non-normal returns (skew & kurtosis)
    # Var(SR) ≈ (1 - skew*SR + (kurtosis-1)/4 * SR^2) / (T-1)
    sr_var = (1 - skew * observed_sharpe + (kurtosis - 1) / 4 * observed_sharpe**2) / max(
        sample_length - 1, 1
    )
    sr_std = np.sqrt(max(sr_var, 1e-10))

    # DSR = P(SR* > E[max(SR)])
    # = Φ((observed - expected_max) / std)
    dsr = float(stats.norm.cdf((observed_sharpe - expected_max_sr) / sr_std))

    result = {
        "dsr": dsr,
        "observed_sharpe": observed_sharpe,
        "expected_max_sharpe": expected_max_sr,
        "n_trials": n_trials,
        "sr_variance": sr_var,
        "passed": dsr > 0.95,
    }

    logger.info(
        "DSR: %.4f (observed=%.3f, expected_max=%.3f, N=%d, passed=%s)",
        dsr,
        observed_sharpe,
        expected_max_sr,
        n_trials,
        result["passed"],
    )
    return result


def _expected_max_sharpe(n_trials: int) -> float:
    """Approximate expected maximum Sharpe from N independent trials.

    Uses the approximation: E[max_N] ≈ Φ^{-1}(1 - 1/N) for large N.

    Fail-closed (odyssey-review CORR-H6): a failure here MUST NOT let the
    multiple-testing penalty collapse to 0. expected_max=0.0 makes
    ``dsr = Φ((observed - 0)/std)`` trivially exceed 0.95 for any positive
    Sharpe — silently dropping the entire point of DSR. Instead return
    ``+inf`` on the degenerate/numerical-failure path so DSR computes to 0.0
    (NO-GO), and log the exception so a scipy upgrade or pathological input
    is visible rather than silently disabling the penalty for all strategies.
    """
    if n_trials <= 1:
        # Single trial → no multiple-testing adjustment is meaningful, but
        # returning 0.0 would make the gate trivially pass. +inf ⇒ DSR=0.0.
        return float("inf")
    # More accurate: (1 - euler_gamma) * Z(1-1/N) + euler_gamma * Z(1-1/(N*e))
    try:
        z1 = float(stats.norm.ppf(1 - 1 / n_trials))
        z2 = float(stats.norm.ppf(1 - 1 / (n_trials * np.e)))
        euler_gamma = 0.5772
        return (1 - euler_gamma) * z1 + euler_gamma * z2
    except (ValueError, OverflowError) as e:
        # Numerical edge case (pathological n_trials, domain error in ppf).
        # +inf ⇒ DSR=0.0 (NO-GO) so the penalty is never silently dropped.
        logger.warning(
            "_expected_max_sharpe numerical failure for n_trials=%d: %s — "
            "returning +inf (DSR will fail-closed to 0.0)",
            n_trials,
            e,
        )
        return float("inf")
