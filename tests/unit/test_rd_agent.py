"""Tests for the Qlib RD-Agent runner skeleton.

Covers the dependency-guard contract (qlib absent → clear failure path), the
baseline pandas factor-evaluation path (works without qlib so the IC
computation logic is testable in CI), and — since wave2 s3 — the real CLI
wiring contract: subprocess invocation with list args (no shell), LLM
credential detection, and graceful degradation to the baseline when the CLI
or credentials are missing.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.rd_agent import (
    DiscoveredFactor,
    QlibNotAvailableError,
    RDAgentCliUnavailableError,
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

    def test_llm_defaults(self):
        cfg = RDAgentConfig()
        assert cfg.llm_backend == "litellm"
        assert cfg.chat_model == ""
        assert cfg.llm_timeout_seconds == pytest.approx(300.0)
        assert cfg.cli_timeout_seconds == pytest.approx(600.0)


class TestRDAgentCliWiring:
    """wave2 s3: real rdagent CLI invocation contract (T-s3-01)."""

    @staticmethod
    def _force_available(monkeypatch):
        monkeypatch.setattr(RDAgentRunner, "check_available", staticmethod(lambda: (True, "")))

    def test_cli_available_reports_missing(self, monkeypatch):
        monkeypatch.setattr(
            RDAgentRunner,
            "cli_available",
            staticmethod(lambda: (False, "rdagent CLI not found on PATH")),
        )
        runner = RDAgentRunner()
        ok, msg = runner.cli_available()
        assert ok is False
        assert "rdagent" in msg

    def test_llm_config_from_env_without_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_API_KEY", raising=False)
        runner = RDAgentRunner()
        assert runner._llm_config_from_env() is None

    def test_llm_config_from_env_reads_key_and_model(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("CHAT_MODEL", "gpt-4o-mini")
        runner = RDAgentRunner()
        cfg = runner._llm_config_from_env()
        assert cfg is not None
        assert cfg["model"] == "gpt-4o-mini"
        assert cfg["backend"] == "litellm"

    def test_discover_factors_degrades_without_cli(self, monkeypatch, caplog):
        """No CLI on PATH → baseline evaluation + info log (not an error)."""
        import logging

        caplog.set_level(logging.INFO, logger="quantflow.strategy.rd_agent")
        self._force_available(monkeypatch)
        monkeypatch.setattr(RDAgentRunner, "cli_available", staticmethod(lambda: (False, "no")))
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_API_KEY", raising=False)
        runner = RDAgentRunner(RDAgentConfig(ic_threshold=0.0))
        factors = runner.discover_factors(_make_ohlcv())
        assert len(factors) == 5  # baseline path ran
        assert any("baseline" in r.message for r in caplog.records)

    def test_discover_factors_uses_cli_when_available(self, monkeypatch):
        """CLI + LLM key present → CLI path returns parsed factors."""
        self._force_available(monkeypatch)
        monkeypatch.setattr(
            RDAgentRunner,
            "cli_available",
            staticmethod(lambda: (True, "/fake/rdagent")),
        )
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        df = _make_ohlcv()

        payload = [
            {"name": "llm_alpha_1", "formula": "close.rolling(7).mean()", "ic": 0.051, "rank_ic": 0.047},
            {"name": "llm_alpha_2", "formula": "volume.pct_change(3)", "ic": 0.012, "rank_ic": 0.010},
        ]
        runner = RDAgentRunner(RDAgentConfig(ic_threshold=0.03))

        def _fake_run(cmd, **kwargs):
            # SECURITY: list args only — no shell=True ever.
            assert isinstance(cmd, list)
            assert kwargs.get("shell") is None or kwargs["shell"] is False
            # Emulate CLI writing output JSON (never stderr success).
            out = Path("data/rdagent_work/factors_output.json")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload), encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        factors = runner.discover_factors(df)
        assert len(factors) == 2
        assert factors[0].name == "llm_alpha_1"
        assert factors[0].selected is True  # 0.051 > 0.03
        assert factors[1].selected is False

    def test_cli_timeout_degrades_to_baseline(self, monkeypatch):
        """CLI timeout → baseline + warning (fail-safe, not crash)."""
        self._force_available(monkeypatch)
        monkeypatch.setattr(
            RDAgentRunner,
            "cli_available",
            staticmethod(lambda: (True, "/fake/rdagent")),
        )
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        def _timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=[], timeout=1)

        monkeypatch.setattr(subprocess, "run", _timeout)
        runner = RDAgentRunner(RDAgentConfig(ic_threshold=0.0))
        factors = runner.discover_factors(_make_ohlcv())
        assert len(factors) == 5  # baseline fallback

    def test_cli_error_degrades_to_baseline(self, monkeypatch):
        """CLI nonzero exit → baseline + warning (no silent empty)."""
        self._force_available(monkeypatch)
        monkeypatch.setattr(
            RDAgentRunner,
            "cli_available",
            staticmethod(lambda: (True, "/fake/rdagent")),
        )
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        def _fail(*args, **kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")

        monkeypatch.setattr(subprocess, "run", _fail)
        runner = RDAgentRunner(RDAgentConfig(ic_threshold=0.0))
        factors = runner.discover_factors(_make_ohlcv())
        assert len(factors) == 5  # baseline fallback

    def test_run_rdagent_cli_raises_without_credentials(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_API_KEY", raising=False)
        monkeypatch.setattr(
            RDAgentRunner,
            "cli_available",
            staticmethod(lambda: (True, "/fake/rdagent")),
        )
        runner = RDAgentRunner()
        with pytest.raises(RDAgentCliUnavailableError, match="credentials"):
            runner._run_rdagent_cli(_make_ohlcv())

    def test_cli_never_uses_shell(self, monkeypatch):
        """Static guard: subprocess.run uses list args, never shell=True (T-s3-01 security)."""
        source = Path("quantflow/strategy/rd_agent.py").read_text(encoding="utf-8")
        # Find the subprocess.run call block and assert no shell= argument is passed.
        run_idx = source.index("subprocess.run(")
        run_block = source[run_idx : run_idx + 400]
        assert "shell=True" not in run_block
        assert "shell=" not in run_block
        assert "cmd," in run_block  # list command vector
