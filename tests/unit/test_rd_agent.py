"""Tests for the Qlib RD-Agent runner skeleton.

Covers the dependency-guard contract (qlib absent → clear failure path) and
the baseline pandas factor-evaluation path (works without qlib so the IC
computation logic is testable in CI).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.rd_agent import (
    DiscoveredFactor,
    QlibNotAvailableError,
    RDAgentConfig,
    RDAgentRunner,
)


def _make_ohlcv(n: int = 120, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 * (1.0 + rng.standard_normal(n).cumsum() * 0.01)
    close = np.maximum(close, 1.0)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1000.0,
        },
        index=idx,
    )


class TestRDAgentRunnerAvailability:
    def test_check_available_returns_tuple(self):
        result = RDAgentRunner.check_available()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)

    def test_unavailable_raises_with_install_hint(self, monkeypatch):
        """When qlib is not importable, discover_factors fails fast."""
        import builtins

        real_import = builtins.__import__

        def _block_qlib(name, *args, **kwargs):
            if name == "qlib" or name.startswith("qlib."):
                raise ImportError("simulated: qlib not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _block_qlib)

        runner = RDAgentRunner()
        available, msg = runner.check_available()
        assert available is False
        assert "pip install" in msg
        assert "qlib" in msg

        with pytest.raises(QlibNotAvailableError, match="qlib is not installed"):
            runner.discover_factors(_make_ohlcv())


class TestRDAgentRunnerBaselineEvaluation:
    """The baseline pandas path runs without qlib (mocked-available)."""

    @staticmethod
    def _force_available(monkeypatch):
        monkeypatch.setattr(RDAgentRunner, "check_available", staticmethod(lambda: (True, "")))

    def test_discover_factors_returns_list(self, monkeypatch):
        self._force_available(monkeypatch)
        runner = RDAgentRunner(RDAgentConfig(ic_threshold=0.0))
        factors = runner.discover_factors(_make_ohlcv())
        assert isinstance(factors, list)
        assert len(factors) == 5
        assert all(isinstance(f, DiscoveredFactor) for f in factors)
        names = {f.name for f in factors}
        assert "momentum_5" in names and "volatility_20" in names

    def test_factors_carry_ic_metrics(self, monkeypatch):
        self._force_available(monkeypatch)
        runner = RDAgentRunner(RDAgentConfig(ic_threshold=0.0))
        factors = runner.discover_factors(_make_ohlcv())
        for f in factors:
            # IC must be a finite float (not NaN)
            assert isinstance(f.ic, float)
            assert np.isfinite(f.ic)
            assert isinstance(f.rank_ic, float)

    def test_selection_gate_marks_factors_above_threshold(self, monkeypatch):
        self._force_available(monkeypatch)
        # Very low threshold → all factors selected
        runner = RDAgentRunner(RDAgentConfig(ic_threshold=0.0))
        factors = runner.discover_factors(_make_ohlcv())
        assert all(f.selected for f in factors)

        # Impossible threshold → none selected
        runner2 = RDAgentRunner(RDAgentConfig(ic_threshold=10.0))
        factors2 = runner2.discover_factors(_make_ohlcv())
        assert not any(f.selected for f in factors2)

    def test_empty_dataframe_returns_empty(self, monkeypatch):
        self._force_available(monkeypatch)
        runner = RDAgentRunner()
        assert runner.discover_factors(pd.DataFrame()) == []

    def test_missing_close_returns_empty(self, monkeypatch):
        self._force_available(monkeypatch)
        runner = RDAgentRunner()
        df = pd.DataFrame({"open": [1.0, 2.0]})
        assert runner.discover_factors(df) == []


class TestRDAgentConfig:
    def test_defaults_match_blueprint_acceptance(self):
        cfg = RDAgentConfig()
        # Blueprint E13-S1: 5+ factors with IC > 0.03
        assert cfg.ic_threshold == pytest.approx(0.03)
        assert cfg.min_selected == 5
