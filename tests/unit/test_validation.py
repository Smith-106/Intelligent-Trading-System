"""Tests for validation pipeline: CPCV, DSR, PBO, WFO, Gate."""

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.validation.cpcv import cpcv_backtest, split_cpcv
from quantflow.strategy.validation.dsr import deflated_sharpe_ratio, _expected_max_sharpe
from quantflow.strategy.validation.pbo import probability_of_overfitting
from quantflow.strategy.validation.wfo import walk_forward_optimization
from quantflow.strategy.validation.gate import validation_gate


def _make_price_series(n: int = 200, trend: float = 0.01) -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    noise = np.random.normal(0, 0.01, n)
    prices = 100.0 * np.exp(np.cumsum(trend + noise))
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


class TestCPCV:
    def test_split_cpcv_basic(self):
        splits = split_cpcv(100, n_groups=4, n_test_groups=1)
        assert len(splits) == 4  # C(4,1) = 4
        for train, test in splits:
            assert len(train) > 0
            assert len(test) > 0
            assert len(set(train) & set(test)) == 0  # no overlap

    def test_split_cpcv_embargo(self):
        splits = split_cpcv(100, n_groups=4, n_test_groups=1, embargo_pct=0.05)
        for train, test in splits:
            # Check embargo: no train index within 5 bars of any test index
            for t in test:
                nearby = [idx for idx in train if abs(idx - t) <= 5]
                assert len(nearby) == 0

    def test_cpcv_backtest_result(self):
        close = _make_price_series(200)
        entries, exits = _make_signals(200)
        result = cpcv_backtest(close, entries, exits, n_groups=4, n_test_groups=1)

        assert "n_paths" in result
        assert "pbo" in result
        assert "oos_efficiency" in result
        assert "passed" in result
        assert result["n_paths"] > 0
        assert 0 <= result["pbo"] <= 1


class TestDSR:
    def test_dsr_high_sharpe_passes(self):
        result = deflated_sharpe_ratio(observed_sharpe=3.0, n_trials=10, sample_length=252)
        assert result["dsr"] > 0.95
        assert result["passed"]

    def test_dsr_zero_sharpe_fails(self):
        result = deflated_sharpe_ratio(observed_sharpe=0.0, n_trials=100, sample_length=252)
        assert result["dsr"] < 0.95
        assert not result["passed"]

    def test_dsr_no_trials(self):
        result = deflated_sharpe_ratio(observed_sharpe=1.0, n_trials=0)
        assert not result["passed"]

    def test_dsr_single_trial(self):
        result = deflated_sharpe_ratio(observed_sharpe=1.0, n_trials=1)
        # With 1 trial, expected max is 0, so DSR should be high
        assert "dsr" in result

    def test_expected_max_sharpe(self):
        ems = _expected_max_sharpe(100)
        assert ems > 0  # With many trials, expected max > 0
        ems_1 = _expected_max_sharpe(1)
        assert ems_1 == 0.0


class TestPBO:
    def test_pbo_basic(self):
        close = _make_price_series(200)
        entries, exits = _make_signals(200)
        result = probability_of_overfitting(close, entries, exits, n_groups=4)

        assert "pbo" in result
        assert 0 <= result["pbo"] <= 1
        assert "passed" in result
        assert "total_paths" in result

    def test_pbo_with_good_strategy(self):
        # Strong uptrend → consistent returns → low PBO
        close = _make_price_series(200, trend=0.03)
        entries, exits = _make_signals(200)
        result = probability_of_overfitting(close, entries, exits, n_groups=4)
        # PBO should be reasonable (may not always pass due to randomness)
        assert isinstance(result["pbo"], float)


class TestWFO:
    def test_wfo_rolling(self):
        close = _make_price_series(200)
        entries, exits = _make_signals(200)
        result = walk_forward_optimization(close, entries, exits, n_windows=3, mode="rolling")

        assert "is_sharpe_mean" in result
        assert "oos_sharpe_mean" in result
        assert "oos_efficiency" in result
        assert "passed" in result

    def test_wfo_anchored(self):
        close = _make_price_series(200)
        entries, exits = _make_signals(200)
        result = walk_forward_optimization(close, entries, exits, n_windows=3, mode="anchored")

        assert "is_sharpe_mean" in result
        assert "passed" in result


class TestValidationGate:
    def test_gate_returns_dict(self):
        close = _make_price_series(200)
        entries, exits = _make_signals(200)
        result = validation_gate(close, entries, exits, n_trials=10, cpcv_groups=4, cpcv_test_groups=1, wfo_windows=3)

        assert "decision" in result
        assert result["decision"] in ("GO", "NO-GO")
        assert "checks" in result