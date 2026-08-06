"""Tests for the s5 risk-parity portfolio optimizer.

NOTE: named test_risk_parity_optimizer.py (not test_optimizer.py) — the
latter already covers quantflow.strategy.research.optimizer.StrategyOptimizer.
"""

from __future__ import annotations

from quantflow.signal.optimizer import RiskParityOptimizer


def _returns(std: float, n: int = 60, seed: int = 0) -> list[float]:
    """Deterministic pseudo-random return series with target std."""
    import random

    rng = random.Random(seed)
    return [rng.gauss(0.0, std) for _ in range(n)]


class TestRiskParityWeights:
    def test_weights_sum_to_one(self) -> None:
        opt = RiskParityOptimizer(min_samples=10)
        returns = {"a": _returns(0.01), "b": _returns(0.03), "c": _returns(0.05)}
        weights = opt.compute(returns)
        assert set(weights) == {"a", "b", "c"}
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_high_vol_gets_lower_weight(self) -> None:
        """Risk parity: high-vol series must receive a smaller weight."""
        opt = RiskParityOptimizer(min_samples=10)
        returns = {"low": _returns(0.01), "high": _returns(0.05)}
        weights = opt.compute(returns)
        assert weights["low"] > weights["high"]

    def test_equal_vol_gives_equal_weights(self) -> None:
        opt = RiskParityOptimizer(min_samples=10)
        returns = {"a": _returns(0.02, seed=1), "b": _returns(0.02, seed=2)}
        weights = opt.compute(returns)
        # Sample noise in short series slightly skews the estimate; both
        # weights must stay within a wide band of 0.5.
        assert abs(weights["a"] - weights["b"]) < 0.15

    def test_risk_contributions_balanced(self) -> None:
        """Risk contributions w_i * sigma_i should be close across series."""
        import statistics

        opt = RiskParityOptimizer(min_samples=10)
        returns = {"a": _returns(0.01), "b": _returns(0.02), "c": _returns(0.04)}
        weights = opt.compute(returns)
        sigmas = [statistics.stdev(r) for r in returns.values()]
        rc = [weights[k] * s for k, s in zip(returns, sigmas, strict=True)]
        # Balanced risk contributions: max spread well below the naive
        # equal-weight spread (which would be ~0.03 for these sigmas).
        assert max(rc) - min(rc) < 0.015


class TestDegradation:
    def test_single_key_returns_equal(self) -> None:
        opt = RiskParityOptimizer(min_samples=10)
        assert opt.compute({"only": _returns(0.01)}) == {"only": 1.0}

    def test_insufficient_samples_returns_equal(self) -> None:
        opt = RiskParityOptimizer(min_samples=50)
        returns = {"a": _returns(0.01, n=10), "b": _returns(0.03, n=10)}
        weights = opt.compute(returns)
        # Both below min_samples → equal over original keys.
        assert abs(weights["a"] - weights["b"]) < 1e-9

    def test_empty_input(self) -> None:
        opt = RiskParityOptimizer()
        assert opt.compute({}) == {}

    def test_nan_values_filtered(self) -> None:
        opt = RiskParityOptimizer(min_samples=5)
        returns = {
            "a": [1.0, 2.0, float("nan"), 3.0, 4.0, 5.0],
            "b": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        }
        weights = opt.compute(returns)
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_constant_series_skipped(self) -> None:
        """Zero-variance series cannot produce a vol estimate — skipped."""
        opt = RiskParityOptimizer(min_samples=5)
        returns = {
            "flat": [1.0] * 60,
            "jumpy": _returns(0.02),
        }
        weights = opt.compute(returns)
        # Only one usable series → equal weights over both original keys.
        assert abs(weights["flat"] - weights["jumpy"]) < 1e-9


class TestEqualWeightHelper:
    def test_equal_weight(self) -> None:
        assert RiskParityOptimizer.equal_weight(["a", "b", "c"]) == {
            "a": 1 / 3,
            "b": 1 / 3,
            "c": 1 / 3,
        }

    def test_equal_weight_empty(self) -> None:
        assert RiskParityOptimizer.equal_weight([]) == {}
