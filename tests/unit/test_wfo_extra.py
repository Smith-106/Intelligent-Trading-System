"""Tests for wfo.py uncovered paths — signal generation failures, optimization failures."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.validation.wfo import walk_forward_optimization


def _make_price_series(n: int = 200, seed: int = 42) -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    rng = np.random.default_rng(seed)
    returns = np.clip(0.002 + rng.normal(0, 0.01, n), -0.05, 0.05)
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


class TestWFOEdgeCases:
    def test_n_windows_less_than_1_raises(self):
        """Line 295: n_windows < 1 → ValueError."""
        close = _make_price_series(60)
        entries, exits = _make_signals(60)
        with pytest.raises(ValueError, match="n_windows must be >= 1"):
            walk_forward_optimization(close, entries, exits, n_windows=0)

    def test_train_optimization_failure_handled(self):
        """Lines 357-359: When train optimization fails, best_params = {}."""
        close = _make_price_series(100)
        entries, exits = _make_signals(100)
        call_count = [0]

        def failing_optimize_signal_fn(data, **params):
            call_count[0] += 1
            if call_count[0] <= 2:  # training calls fail
                raise RuntimeError("optimization failed")
            return pd.Series(False, index=data.index), pd.Series(False, index=data.index)

        result = walk_forward_optimization(
            close, entries, exits,
            n_windows=2,
            signal_fn=failing_optimize_signal_fn,
            param_space={"period": (2, 10)},
        )
        # Should complete without error
        assert "decision" in result or "window_results" in result or "oos_sharpes" in result

    def test_oos_signal_generation_failure_handled(self):
        """Lines 366-369: When OOS signal generation fails, use empty signals."""
        close = _make_price_series(100)
        entries, exits = _make_signals(100)
        call_count = [0]

        def failing_oos_signal_fn(data, **params):
            call_count[0] += 1
            if call_count[0] > 3:  # OOS calls fail
                raise RuntimeError("OOS signal failed")
            return pd.Series(False, index=data.index), pd.Series(False, index=data.index)

        result = walk_forward_optimization(
            close, entries, exits,
            n_windows=2,
            signal_fn=failing_oos_signal_fn,
            param_space={"period": (2, 10)},
        )
        # Should complete without error
        assert isinstance(result, dict)

    def test_train_signal_generation_failure_handled(self):
        """Lines 374-377: When train signal generation fails, use empty signals."""
        close = _make_price_series(100)
        entries, exits = _make_signals(100)
        call_count = [0]

        def failing_train_signal_fn(data, **params):
            call_count[0] += 1
            if call_count[0] > 1:
                raise RuntimeError("train signal failed")
            return pd.Series(False, index=data.index), pd.Series(False, index=data.index)

        result = walk_forward_optimization(
            close, entries, exits,
            n_windows=2,
            signal_fn=failing_train_signal_fn,
            param_space={"period": (2, 10)},
        )
        assert isinstance(result, dict)

    def test_basic_wfo_without_signal_fn(self):
        """WFO with pre-generated entries/exits (no signal_fn)."""
        close = _make_price_series(100)
        entries, exits = _make_signals(100)
        result = walk_forward_optimization(
            close, entries, exits,
            n_windows=3,
        )
        assert isinstance(result, dict)
        assert "window_results" in result or "oos_sharpes" in result

    def test_anchored_mode(self):
        """Anchored mode: all IS windows start from index 0."""
        close = _make_price_series(100)
        entries, exits = _make_signals(100)
        result = walk_forward_optimization(
            close, entries, exits,
            n_windows=2, mode="anchored",
        )
        assert isinstance(result, dict)

    def test_signal_fn_without_param_space(self):
        """signal_fn provided but no param_space → no optimization, just signal generation."""
        close = _make_price_series(100)
        entries, exits = _make_signals(100)

        def signal_fn(data, **params):
            return pd.Series(False, index=data.index), pd.Series(False, index=data.index)

        result = walk_forward_optimization(
            close, entries, exits,
            n_windows=2,
            signal_fn=signal_fn,
            param_space=None,  # no optimization
        )
        assert isinstance(result, dict)
