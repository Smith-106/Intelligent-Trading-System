"""Additional CPCV core path tests — P1-1."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.validation.cpcv import _cpcv_failure_result, _sanitize_metric_array, cpcv_backtest, split_cpcv


def _make_price_series(n: int = 200, trend: float = 0.002) -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    rng = np.random.default_rng(42)
    returns = np.clip(trend + rng.normal(0, 0.01, n), -0.05, 0.05)
    prices = 100.0 * pd.Series(1.0 + returns, index=dates).cumprod().to_numpy()
    return pd.Series(prices, index=dates)


def _make_signals(n: int) -> tuple[pd.Series, pd.Series]:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    entries = pd.Series(False, index=dates)
    exits = pd.Series(False, index=dates)
    for i in range(0, n, 20):
        if i < n:
            entries.iloc[i] = True
    for i in range(10, n, 20):
        if i < n:
            exits.iloc[i] = True
    return entries, exits


class TestCPCVSplitEdgeCases:
    def test_split_rejects_n_groups_less_than_2(self):
        with pytest.raises(ValueError, match="at least 2 groups"):
            split_cpcv(100, n_groups=1, n_test_groups=1)

    def test_split_rejects_n_test_groups_zero(self):
        with pytest.raises(ValueError, match="at least 1 test group"):
            split_cpcv(100, n_groups=4, n_test_groups=0)

    def test_split_rejects_n_test_groups_gte_n_groups(self):
        with pytest.raises(ValueError, match="fewer than total"):
            split_cpcv(100, n_groups=4, n_test_groups=4)

    def test_split_rejects_n_bars_less_than_2(self):
        with pytest.raises(ValueError, match="at least 2 bars"):
            split_cpcv(1, n_groups=4, n_test_groups=1)

    def test_split_rejects_n_bars_less_than_n_groups(self):
        """When n_bars < n_groups, the earlier check rejects first."""
        with pytest.raises(ValueError, match="at least"):
            split_cpcv(2, n_groups=4, n_test_groups=1)

    def test_split_with_larger_test_groups(self):
        splits = split_cpcv(100, n_groups=6, n_test_groups=3)
        # C(6,3) = 20 paths
        assert len(splits) == 20
        for train, test in splits:
            assert len(train) > 0
            assert len(test) > 0

    def test_split_no_embargo_when_pct_is_zero(self):
        splits = split_cpcv(100, n_groups=4, n_test_groups=1, embargo_pct=0.0)
        # With embargo_pct=0, min embargo_bars = max(1, 0) = 1
        # So there's still 1-bar embargo (the minimum)
        assert len(splits) == 4


class TestSanitizeMetricArray:
    def test_replaces_nan(self):
        arr = _sanitize_metric_array([1.0, float("nan"), 3.0])
        assert arr[1] == 0.0

    def test_replaces_posinf(self):
        arr = _sanitize_metric_array([1.0, float("inf"), 3.0])
        assert arr[1] == 0.0

    def test_replaces_neginf(self):
        arr = _sanitize_metric_array([1.0, float("-inf"), 3.0])
        assert arr[1] == 0.0

    def test_preserves_finite(self):
        arr = _sanitize_metric_array([1.0, 2.5, -3.0])
        np.testing.assert_array_equal(arr, [1.0, 2.5, -3.0])


class TestCPCVFailureResult:
    def test_default_failure(self):
        result = _cpcv_failure_result("test reason")
        assert result["n_paths"] == 0
        assert result["pbo"] == 1.0
        assert result["oos_efficiency"] == 0.0
        assert result["passed"] is False
        assert result["reason"] == "test reason"
        assert result["optimized"] is False
        assert result["oos_recomputed"] is False

    def test_failure_with_optimized_flag(self):
        result = _cpcv_failure_result("bad", optimized=True, oos_recomputed=True)
        assert result["optimized"] is True
        assert result["oos_recomputed"] is True


class TestCPCVBacktestWithSignalFn:
    def test_cpcv_with_signal_fn_and_param_space(self):
        """CPCV with optimization: signal_fn + param_space should trigger optimization path."""
        close = _make_price_series(100)
        entries, exits = _make_signals(100)
        data = pd.DataFrame({"close": close}, index=close.index)
        param_space = {"threshold": (0.5, 2.0)}

        def signal_fn(frame, **params):
            threshold = params.get("threshold", 1.0)
            ents = frame["close"] > frame["close"].rolling(10).mean() * threshold
            exts = frame["close"] < frame["close"].rolling(10).mean() * threshold
            return ents.fillna(False), exts.fillna(False)

        result = cpcv_backtest(
            close, entries, exits,
            n_groups=4, n_test_groups=1,
            signal_fn=signal_fn,
            param_space=param_space,
            data=data,
            n_trials=2,
            method="random",
        )

        assert result["n_paths"] > 0
        assert result["optimized"] is True
        assert "path_results" in result

    def test_cpcv_with_signal_fn_no_param_space(self):
        """signal_fn without param_space: OOS recomputed but not optimized."""
        close = _make_price_series(60)
        entries, exits = _make_signals(60)
        data = pd.DataFrame({"close": close}, index=close.index)

        def signal_fn(frame, **params):
            ents = frame["close"] > frame["close"].rolling(5).mean()
            exts = ~ents
            return ents.fillna(False), exts.fillna(False)

        result = cpcv_backtest(
            close, entries, exits,
            n_groups=3, n_test_groups=1,
            signal_fn=signal_fn,
            data=data,
        )

        assert result["n_paths"] > 0
        assert result["optimized"] is False
        assert result["oos_recomputed"] is True

    def test_cpcv_train_optimization_failure_handled(self, monkeypatch):
        """When optimization fails on a path, best_params should default to {}."""
        close = _make_price_series(60)
        entries, exits = _make_signals(60)
        data = pd.DataFrame({"close": close}, index=close.index)
        param_space = {"threshold": (0.5, 2.0)}

        def signal_fn(frame, **params):
            ents = pd.Series(False, index=frame.index)
            exts = pd.Series(False, index=frame.index)
            return ents, exts

        # Patch the optimizer where it's imported inside cpcv_backtest
        import quantflow.strategy.research.optimizer as opt_mod

        class FailingOptimizer:
            def __init__(self, engine=None):
                pass
            def optimize(self, *args, **kwargs):
                raise RuntimeError("optimization failed")

        monkeypatch.setattr(opt_mod, "StrategyOptimizer", FailingOptimizer)

        result = cpcv_backtest(
            close, entries, exits,
            n_groups=3, n_test_groups=1,
            signal_fn=signal_fn,
            param_space=param_space,
            data=data,
            n_trials=2,
        )

        # Should still complete (with failures caught)
        assert result["n_paths"] > 0
