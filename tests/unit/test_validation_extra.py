"""Additional validation gate and CPCV path tests — covers uncovered lines."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantflow.strategy.validation import gate as gate_module
from quantflow.strategy.validation.cpcv import cpcv_backtest
from quantflow.strategy.validation.gate import validation_gate


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


class TestValidationGateWinRate:
    def test_gate_blocks_low_win_rate(self, monkeypatch):
        """When win_rate_threshold is set and avg win rate is below, gate blocks."""
        close = _make_price_series(60)
        entries, exits = _make_signals(60)

        monkeypatch.setattr(
            gate_module,
            "cpcv_backtest",
            lambda *a, **kw: {
                "passed": True,
                "pbo": 0.1,
                "path_results": [
                    {"oos_sharpe": 1.2, "oos_win_rate": 0.3},
                    {"oos_sharpe": 0.8, "oos_win_rate": 0.35},
                ],
            },
        )
        monkeypatch.setattr(
            gate_module,
            "deflated_sharpe_ratio",
            lambda **kw: {"passed": True, "dsr": 0.99},
        )
        monkeypatch.setattr(
            gate_module,
            "walk_forward_optimization",
            lambda *a, **kw: {"passed": True, "oos_efficiency": 0.8},
        )

        result = validation_gate(close, entries, exits, win_rate_threshold=0.5)

        assert result["decision"] == "NO-GO"
        assert "win_rate" in result["reason"]
        assert result["checks"]["win_rate"]["passed"] is False

    def test_gate_passes_with_sufficient_win_rate(self, monkeypatch):
        """When avg win rate meets threshold, gate continues."""
        close = _make_price_series(60)
        entries, exits = _make_signals(60)

        monkeypatch.setattr(
            gate_module,
            "cpcv_backtest",
            lambda *a, **kw: {
                "passed": True,
                "pbo": 0.1,
                "path_results": [
                    {"oos_sharpe": 1.5, "oos_win_rate": 0.7},
                    {"oos_sharpe": 1.2, "oos_win_rate": 0.6},
                ],
            },
        )
        monkeypatch.setattr(
            gate_module,
            "deflated_sharpe_ratio",
            lambda **kw: {"passed": True, "dsr": 0.99},
        )
        monkeypatch.setattr(
            gate_module,
            "walk_forward_optimization",
            lambda *a, **kw: {"passed": True, "oos_efficiency": 0.8},
        )

        result = validation_gate(close, entries, exits, win_rate_threshold=0.5)

        assert result["decision"] == "GO"
        assert result["checks"]["win_rate"]["passed"] is True


class TestCPCVSignalGenerationFailure:
    def test_cpcv_handles_train_signal_failure(self, monkeypatch):
        """When train signal generation fails, CPCV should continue with empty signals."""
        close = _make_price_series(60)
        entries, exits = _make_signals(60)

        call_count = [0]

        def failing_signal_fn(frame, **params):
            call_count[0] += 1
            if call_count[0] <= 3:  # first few calls (train) fail
                raise RuntimeError("signal generation failed")
            return pd.Series(False, index=frame.index), pd.Series(False, index=frame.index)

        result = cpcv_backtest(
            close,
            entries,
            exits,
            n_groups=3,
            n_test_groups=1,
            signal_fn=failing_signal_fn,
        )

        assert result["n_paths"] > 0

    def test_cpcv_handles_oos_signal_failure(self, monkeypatch):
        """When OOS signal generation fails, CPCV should use empty signals and continue."""
        close = _make_price_series(60)
        entries, exits = _make_signals(60)

        call_count = [0]

        def failing_oos_signal_fn(frame, **params):
            call_count[0] += 1
            if call_count[0] > 2:  # later calls (OOS) fail
                raise RuntimeError("OOS signal failed")
            return pd.Series(False, index=frame.index), pd.Series(False, index=frame.index)

        result = cpcv_backtest(
            close,
            entries,
            exits,
            n_groups=3,
            n_test_groups=1,
            signal_fn=failing_oos_signal_fn,
        )

        assert result["n_paths"] > 0
