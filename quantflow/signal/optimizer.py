"""Portfolio-level optimization — risk parity / mean-variance allocation (s5).

- ``RiskParityOptimizer``: equal risk contribution weights — each
  asset/strategy's volatility contribution to the portfolio is balanced.
- ``MeanVarianceOptimizer``: global minimum-variance weights — w proportional
  to the inverse covariance times the ones vector (no return forecast needed).

Both expose the same ``compute(returns) -> weights`` contract so the engine
can switch methods purely via ``portfolio_optimization.method``. Default OFF
in the engine (``portfolio_optimization.enabled=False``) — this module is
only invoked when a user opts in, so backtests/live runs that do not enable
it keep their exact prior behavior.
"""

from __future__ import annotations

import logging
import math
import statistics

import numpy as np
from scipy.optimize import minimize

logger = logging.getLogger(__name__)


class RiskParityOptimizer:
    """Solve risk-parity weights for a set of return series.

    Objective: minimize the pairwise squared deviation of risk
    contributions ``(w_i * sigma_i - w_j * sigma_j)^2`` so that each
    series contributes equally to portfolio volatility. Solved with
    SLSQP under ``sum(w) = 1`` and ``w >= 0``, initialized at equal
    weight.

    Fail-closed: any degenerate input (fewer than 2 series, insufficient
    samples, singular covariance, solver failure) returns equal weights
    rather than raising — a brand-new session never over-concentrates
    into a single strategy.
    """

    def __init__(self, min_samples: int = 30, vol_annualization: int = 365) -> None:
        self._min_samples = min_samples
        self._vol_annualization = vol_annualization

    @staticmethod
    def equal_weight(keys: list[str]) -> dict[str, float]:
        """Uniform weights across keys (fallback for any degenerate input)."""
        if not keys:
            return {}
        w = 1.0 / len(keys)
        return {k: w for k in keys}

    def _annualized_vol(self, returns: list[float]) -> float | None:
        """Annualized sample volatility of a return series, or None."""
        values = [float(x) for x in returns if not math.isnan(x)]
        if len(values) < 2:
            return None
        sigma = statistics.stdev(values)
        if sigma <= 0:
            return None
        return float(sigma * (self._vol_annualization**0.5))

    def compute(self, returns: dict[str, list[float]]) -> dict[str, float]:
        """Risk-parity weights for the given per-key return series.

        Keys with insufficient samples (< min_samples) are dropped; if
        fewer than 2 keys remain, equal weights are returned over the
        ORIGINAL keys (fail-safe: a partial history never over-weights).
        """
        keys = list(returns.keys())
        if len(keys) < 2:
            return self.equal_weight(keys)

        vols: dict[str, float] = {}
        for key in keys:
            series = returns.get(key) or []
            if len(series) < self._min_samples:
                continue
            sigma = self._annualized_vol(series)
            if sigma is not None:
                vols[key] = sigma

        if len(vols) < 2:
            return self.equal_weight(keys)

        names = list(vols.keys())
        sigma_vec = np.array([vols[k] for k in names], dtype=float)

        def objective(w: np.ndarray) -> float:
            rc = w * sigma_vec  # risk contributions
            # Pairwise squared deviation of risk contributions.
            diff = rc[:, None] - rc[None, :]
            return float(np.sum(diff**2) / 2.0)  # symmetric, halve

        n = len(names)
        x0 = np.full(n, 1.0 / n)
        bounds = [(0.0, 1.0)] * n
        constraints = {"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}

        try:
            result = minimize(
                objective,
                x0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"ftol": 1e-9, "maxiter": 200},
            )
            if not result.success:
                logger.warning("RiskParityOptimizer: solver failed (%s) — equal weights", result.message)
                return self.equal_weight(keys)
            w = np.clip(result.x, 0.0, None)
            total = float(np.sum(w))
            if total <= 0:
                return self.equal_weight(keys)
            return {name: float(wi) / total for name, wi in zip(names, w, strict=True)}
        except Exception:  # optimizer must never crash the trading loop
            logger.exception("RiskParityOptimizer: unexpected failure — equal weights")
            return self.equal_weight(keys)


class MeanVarianceOptimizer:
    """Solve global minimum-variance weights for a set of return series.

    Weights are proportional to the inverse covariance: ``w = S^-1 * 1``
    normalized so ``sum(w) = 1`` (global min-variance portfolio). No return
    forecast is required — only the covariance structure drives allocation,
    which is more robust than mean-variance with noisy expected-return
    estimates.

    Fail-closed, mirroring RiskParityOptimizer: insufficient samples,
    singular covariance (pinv fallback still failing), zero-variance series
    and any unexpected error all degrade to equal weights — never raises.
    """

    def __init__(self, min_samples: int = 30) -> None:
        self._min_samples = min_samples

    @staticmethod
    def equal_weight(keys: list[str]) -> dict[str, float]:
        """Uniform weights across keys (fallback for any degenerate input)."""
        if not keys:
            return {}
        w = 1.0 / len(keys)
        return {k: w for k in keys}

    def compute(self, returns: dict[str, list[float]]) -> dict[str, float]:
        """Global min-variance weights for the given per-key return series.

        Keys with insufficient samples (< min_samples) or zero variance are
        dropped; if fewer than 2 usable keys remain, equal weights are
        returned over the ORIGINAL keys (fail-safe: a partial history never
        over-concentrates).
        """
        keys = list(returns.keys())
        if len(keys) < 2:
            return self.equal_weight(keys)

        usable: list[str] = []
        series: list[list[float]] = []
        for key in keys:
            values = [float(x) for x in (returns.get(key) or []) if not math.isnan(x)]
            if len(values) < self._min_samples:
                continue
            sigma = statistics.stdev(values)
            if sigma <= 0:
                continue
            usable.append(key)
            series.append(values)

        if len(usable) < 2:
            return self.equal_weight(keys)

        # Series may differ in length (NaN filtering); truncate to the common
        # length so np.cov receives a rectangular matrix.
        min_len = min(len(s) for s in series)
        matrix = np.array([s[:min_len] for s in series], dtype=float)  # n_assets × n_samples
        try:
            cov = np.cov(matrix)
            try:
                inv = np.linalg.inv(cov)
            except np.linalg.LinAlgError:
                # Singular covariance (n_samples <= n_assets): Moore-Penrose
                # pseudo-inverse still yields a valid min-variance-ish weight.
                inv = np.linalg.pinv(cov)
            ones = np.ones(len(usable))
            w = inv @ ones
            total = float(np.sum(w))
            if total <= 0 or not np.all(np.isfinite(w)):
                return self.equal_weight(keys)
            w = np.clip(w, 0.0, None)  # no shorting in this system
            total = float(np.sum(w))
            if total <= 0:  # pragma: no cover - unreachable: clip() keeps sum >= 0; sum==0 implies pre-clip total <= 0 caught by guard above
                return self.equal_weight(keys)  # pragma: no cover
            return {k: float(wi) / total for k, wi in zip(usable, w, strict=True)}
        except Exception:  # optimizer must never crash the trading loop
            logger.exception("MeanVarianceOptimizer: unexpected failure — equal weights")
            return self.equal_weight(keys)
