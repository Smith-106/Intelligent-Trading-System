"""Tests for the s5 follow-up mean-variance (min-variance) optimizer."""

from __future__ import annotations

from quantflow.signal.optimizer import MeanVarianceOptimizer


def _returns(std: float, n: int = 60, seed: int = 0) -> list[float]:
    """Deterministic pseudo-random return series with target std."""
    import random

    rng = random.Random(seed)
    return [rng.gauss(0.0, std) for _ in range(n)]


class TestMeanVarianceWeights:
    def test_weights_sum_to_one(self) -> None:
        opt = MeanVarianceOptimizer(min_samples=10)
        returns = {"a": _returns(0.01), "b": _returns(0.03), "c": _returns(0.05)}
        weights = opt.compute(returns)
        assert set(weights) == {"a", "b", "c"}
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_low_vol_gets_higher_weight(self) -> None:
        """Min-variance: low-vol series must receive a larger weight."""
        opt = MeanVarianceOptimizer(min_samples=10)
        returns = {"low": _returns(0.01), "high": _returns(0.05)}
        weights = opt.compute(returns)
        assert weights["low"] > weights["high"]

    def test_uncorrelated_equal_vol_equal_weights(self) -> None:
        """Longer series damp sample noise; min-variance stays near equal."""
        opt = MeanVarianceOptimizer(min_samples=50)
        returns = {"a": _returns(0.02, n=300, seed=1), "b": _returns(0.02, n=300, seed=2)}
        weights = opt.compute(returns)
        assert abs(weights["a"] - weights["b"]) < 0.2


class TestDegradation:
    def test_single_key_returns_equal(self) -> None:
        opt = MeanVarianceOptimizer(min_samples=10)
        assert opt.compute({"only": _returns(0.01)}) == {"only": 1.0}

    def test_insufficient_samples_returns_equal(self) -> None:
        opt = MeanVarianceOptimizer(min_samples=50)
        returns = {"a": _returns(0.01, n=10), "b": _returns(0.03, n=10)}
        weights = opt.compute(returns)
        assert abs(weights["a"] - weights["b"]) < 1e-9

    def test_empty_input(self) -> None:
        opt = MeanVarianceOptimizer()
        assert opt.compute({}) == {}

    def test_singular_covariance_falls_back_to_equal(self) -> None:
        """n_samples < n_assets → singular covariance → pinv → still equal."""
        opt = MeanVarianceOptimizer(min_samples=3)
        returns = {
            "a": [0.01, 0.02, 0.01, 0.02],
            "b": [0.01, 0.02, 0.01, 0.02],  # identical → degenerate
            "c": [0.01, 0.02, 0.01, 0.02],
            "d": [0.03, 0.04, 0.03, 0.04],
        }
        weights = opt.compute(returns)
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_constant_series_skipped(self) -> None:
        opt = MeanVarianceOptimizer(min_samples=5)
        returns = {
            "flat": [1.0] * 60,
            "jumpy": _returns(0.02),
        }
        weights = opt.compute(returns)
        assert abs(weights["flat"] - weights["jumpy"]) < 1e-9

    def test_nan_values_filtered(self) -> None:
        opt = MeanVarianceOptimizer(min_samples=5)
        returns = {
            "a": [1.0, 2.0, float("nan"), 3.0, 4.0, 5.0],
            "b": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        }
        weights = opt.compute(returns)
        assert abs(sum(weights.values()) - 1.0) < 1e-6
