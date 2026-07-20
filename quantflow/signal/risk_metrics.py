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

        .. warning:: The ``parametric`` (Gaussian) branch systematically
            underestimates tail risk for crypto returns, which are
            leptokurtic (fat-tailed). It is retained only as an auxiliary
            reference; the risk engine's gate (RiskEngine._check_var) uses
            historical CVaR/ES, not this parametric branch. Per Hull,
            McNeil/Frey/Embrechts, and Basel FRTB (ES_97.5 replaced 99% VaR
            as the coheret tail-risk measure since 2019) — prefer
            ``conditional_var`` (ES) for any tail-risk decision (ISS-20260718-004).

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


def bootstrap_cvar(
    returns: pd.Series | np.ndarray,
    confidence: float = 0.95,
    n_bootstrap: int = 1000,
    ci: float = 0.95,
    seed: int = 0,
) -> dict[str, float]:
    """Bootstrap confidence interval for the historical CVaR point estimate.

    DIAGNOSTIC ONLY (deep-research F4 / P1). This does NOT replace the
    historical CVaR gate in risk_engine._check_var — that gate stays on the
    point estimate. Instead it quantifies the *uncertainty* of that point
    estimate by resampling returns with replacement and recomputing CVaR each
    time. A wide interval that straddles ``cvar_limit`` signals the gate's
    verdict is sample-fragile and the operator should collect more data before
    trusting it; a narrow interval on the safe side means the gate is sound.

    Returns a dict with the point estimate and the lower/upper bounds of the
    CVaR confidence interval. Values follow ``conditional_var``'s convention:
    a positive loss MAGNITUDE (e.g. 0.05 = 5% expected tail loss). ``ci_low``
    is the milder (smaller) bound, ``ci_high`` the more severe (larger).

    Anti-pattern avoided (per claude delegate): a Monte-Carlo / parametric
    CVaR replacing the historical main gate. Parametric CVaR violates the
    fat-tail spec (understates tail mass); bootstrap CVaR is asymptotically
    the historical CVaR and adds only a CI, not a competing gate.
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 10:
        return {"point": 0.0, "ci_low": 0.0, "ci_high": 0.0, "n": 0, "n_bootstrap": 0}

    point = conditional_var(r, confidence)
    rng = np.random.default_rng(seed)
    n = len(r)
    samples = np.empty(n_bootstrap, dtype=float)
    for i in range(n_bootstrap):
        idx = rng.integers(0, n, size=n)
        resample = r[idx]
        var = np.percentile(resample, (1 - confidence) * 100)
        samples[i] = -np.mean(resample[resample <= var])
    alpha = (1 - ci) / 2
    ci_low = float(np.percentile(samples, alpha * 100))
    ci_high = float(np.percentile(samples, (1 - alpha) * 100))
    return {
        "point": point,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "n": n,
        "n_bootstrap": n_bootstrap,
    }


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
