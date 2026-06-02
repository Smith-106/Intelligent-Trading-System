"""Risk metrics — VaR, CVaR, drawdown, and related calculations."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def value_at_risk(
    returns: pd.Series | np.ndarray, confidence: float = 0.95, method: str = "historical"
) -> float:
    """Calculate Value at Risk (VaR).

    Parameters
    ----------
    returns : pd.Series or np.ndarray
        Period returns (e.g. daily).
    confidence : float
        Confidence level (0.95 = 95% VaR).
    method : str
        "historical" or "parametric" (Gaussian).

    Returns
    -------
    float
        VaR as a negative fraction (e.g. -0.02 = 2% VaR).
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 10:
        return 0.0

    if method == "parametric":
        mu = np.mean(r)
        sigma = np.std(r, ddof=1)
        from scipy.stats import norm

        var = mu - sigma * norm.ppf(confidence)
    else:
        var = np.percentile(r, (1 - confidence) * 100)

    return float(var)


def conditional_var(returns: pd.Series | np.ndarray, confidence: float = 0.95) -> float:
    """Calculate Conditional VaR (Expected Shortfall).

    Average loss in the worst (1-confidence)% of cases.
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 10:
        return 0.0

    var = np.percentile(r, (1 - confidence) * 100)
    cvar = -np.mean(r[r <= var])
    return float(cvar)


def max_drawdown(equity_curve: pd.Series | np.ndarray) -> float:
    """Calculate maximum drawdown from an equity curve.

    Returns
    -------
    float
        Maximum drawdown as a negative fraction.
    """
    eq = np.asarray(equity_curve, dtype=float)
    if len(eq) < 2:
        return 0.0

    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    return float(np.min(dd))


def sharpe_ratio(
    returns: pd.Series | np.ndarray, risk_free: float = 0.0, periods_per_year: int = 365
) -> float:
    """Annualized Sharpe ratio."""
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 2:
        return 0.0

    excess = r - risk_free / periods_per_year
    if np.std(excess, ddof=1) == 0:
        return 0.0

    return float(np.mean(excess) / np.std(excess, ddof=1) * np.sqrt(periods_per_year))


def sortino_ratio(
    returns: pd.Series | np.ndarray, risk_free: float = 0.0, periods_per_year: int = 365
) -> float:
    """Annualized Sortino ratio (downside deviation only)."""
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 2:
        return 0.0

    target = risk_free / periods_per_year
    downside = r[r < target] - target
    if len(downside) == 0 or np.std(downside, ddof=1) == 0:
        return 0.0

    return float(np.mean(r - target) / np.std(downside, ddof=1) * np.sqrt(periods_per_year))


def calmar_ratio(
    returns: pd.Series | np.ndarray,
    equity_curve: pd.Series | np.ndarray,
    periods_per_year: int = 365,
) -> float:
    """Calmar ratio: annualized return / max drawdown."""
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 2:
        return 0.0

    annual_return = float(np.mean(r) * periods_per_year)
    dd = max_drawdown(equity_curve)

    if dd >= 0:
        return 0.0

    return annual_return / abs(dd)
