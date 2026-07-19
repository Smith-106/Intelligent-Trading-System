"""Tests for quantflow.signal.risk_metrics."""

import numpy as np
import pandas as pd

from quantflow.signal.risk_metrics import (
    bootstrap_cvar,
    conditional_var,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
    value_at_risk,
)


class TestValueAtRisk:
    def test_historical_var(self):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.001, 0.02, 1000))
        var = value_at_risk(returns, confidence=0.95)
        # VaR is returned as a negative fraction (loss)
        assert var < 0

    def test_parametric_var(self):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.001, 0.02, 1000))
        var = value_at_risk(returns, confidence=0.95, method="parametric")
        assert var < 0

    def test_insufficient_data(self):
        returns = pd.Series([0.01])
        assert value_at_risk(returns) == 0.0


class TestConditionalVar:
    def test_cvar_worse_than_var(self):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.001, 0.02, 1000))
        var = value_at_risk(returns)
        cvar = conditional_var(returns)
        # CVaR magnitude should be >= VaR magnitude (both negative)
        assert abs(cvar) >= abs(var)


class TestBootstrapCvar:
    """Bootstrap CVaR confidence interval (deep-research F4 / P1).

    Contract: this is a DIAGNOSTIC that quantifies the uncertainty of the
    historical CVaR point estimate. It does NOT replace the historical CVaR
    gate in risk_engine._check_var (anti-pattern per claude delegate).
    """

    def _returns(self, n: int = 1000, seed: int = 42) -> pd.Series:
        rng = np.random.default_rng(seed)
        # Student-t fat tails: heavier than Gaussian, matches the crypto spec.
        return pd.Series(rng.standard_t(df=4, size=n) * 0.02)

    def test_returns_point_and_ci(self):
        res = bootstrap_cvar(self._returns(), n_bootstrap=200, seed=1)
        assert set(res.keys()) == {"point", "ci_low", "ci_high", "n", "n_bootstrap"}
        assert res["n"] == 1000
        assert res["n_bootstrap"] == 200
        # point estimate equals the standalone historical CVaR
        assert abs(res["point"] - conditional_var(self._returns())) < 1e-12

    def test_ci_brackets_point_estimate(self):
        """The point estimate should fall within (or near) the bootstrap CI."""
        res = bootstrap_cvar(self._returns(), n_bootstrap=500, seed=2)
        # CVaR is a loss MAGNITUDE (positive, matching conditional_var's
        # -np.mean(r[r<=var]) convention). ci_low is the milder bound,
        # ci_high the more severe; the full-sample point sits inside.
        assert (
            res["ci_low"] <= res["point"] <= res["ci_high"]
            or abs(res["point"] - res["ci_low"]) < 0.01
            or abs(res["point"] - res["ci_high"]) < 0.01
        )

    def test_ci_high_is_more_severe_than_ci_low(self):
        res = bootstrap_cvar(self._returns(), n_bootstrap=300, seed=3)
        # both positive loss magnitudes; ci_high is the deeper loss (> ci_low)
        assert res["ci_high"] >= res["ci_low"]

    def test_reproducible_with_seed(self):
        a = bootstrap_cvar(self._returns(), n_bootstrap=100, seed=7)
        b = bootstrap_cvar(self._returns(), n_bootstrap=100, seed=7)
        assert a == b

    def test_different_seeds_produce_different_ci(self):
        a = bootstrap_cvar(self._returns(n=400), n_bootstrap=200, seed=11)
        b = bootstrap_cvar(self._returns(n=400), n_bootstrap=200, seed=12)
        assert a["ci_low"] != b["ci_low"] or a["ci_high"] != b["ci_high"]

    def test_insufficient_data_returns_zeros(self):
        res = bootstrap_cvar(pd.Series([0.01]), n_bootstrap=50, seed=1)
        assert res == {"point": 0.0, "ci_low": 0.0, "ci_high": 0.0, "n": 0, "n_bootstrap": 0}

    def test_nan_returns_filtered(self):
        with_nan = pd.Series([0.01, float("nan"), -0.02, 0.04] * 100)
        res = bootstrap_cvar(with_nan, n_bootstrap=50, seed=1)
        assert res["n_bootstrap"] == 50
        # CVaR is a positive loss magnitude; worst tail here is the -0.02 bars
        assert res["point"] > 0

    def test_wide_ci_for_small_sample_straddles_threshold(self):
        """Small samples should yield a WIDER CI — the diagnostic's whole point."""
        small = self._returns(n=30, seed=5)
        large = self._returns(n=2000, seed=5)
        ci_small = bootstrap_cvar(small, n_bootstrap=400, seed=1)
        ci_large = bootstrap_cvar(large, n_bootstrap=400, seed=1)
        width_small = ci_small["ci_high"] - ci_small["ci_low"]
        width_large = ci_large["ci_high"] - ci_large["ci_low"]
        assert width_small > width_large


class TestMaxDrawdown:
    def test_positive_curve(self):
        equity = pd.Series([100, 110, 120, 130, 140])
        dd = max_drawdown(equity)
        assert dd == 0.0

    def test_drawdown_curve(self):
        equity = pd.Series([100, 120, 90, 110])
        dd = max_drawdown(equity)
        assert dd < 0
        assert abs(dd - (-0.25)) < 0.01

    def test_short_series(self):
        assert max_drawdown(pd.Series([100])) == 0.0


class TestSharpeRatio:
    def test_positive_sharpe(self):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.002, 0.01, 252))
        sr = sharpe_ratio(returns)
        assert sr > 0

    def test_zero_std(self):
        returns = pd.Series([0.0] * 100)
        assert sharpe_ratio(returns) == 0.0


class TestSortinoRatio:
    def test_positive_sortino(self):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.002, 0.01, 252))
        so = sortino_ratio(returns)
        assert so > 0

    def test_sortino_returns_zero_for_single_observation(self):
        assert sortino_ratio(pd.Series([0.01])) == 0.0
