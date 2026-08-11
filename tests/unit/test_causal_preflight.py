"""Tests for causal preflight aggregator."""

from __future__ import annotations

from quantflow.strategy.templates.trend_following import TrendFollowingStrategy
from quantflow.strategy.validation.causal_preflight import run_causal_preflight


def test_empty_input_fails() -> None:
    rep = run_causal_preflight(None)
    assert rep.passed is False
    assert rep.severity_counts.get("high", 0) >= 1


def test_trend_following_static_pass() -> None:
    rep = run_causal_preflight(TrendFollowingStrategy)
    assert isinstance(rep.to_dict(), dict)
    # trend_following is the project baseline — should be clean of masked-agg / shift(-1)
    assert rep.passed is True
    assert rep.severity_counts.get("high", 0) == 0


def test_negative_shift_in_extra_source_fails() -> None:
    bad = "def f(s):\n    return s.shift(-1)\n"
    rep = run_causal_preflight(extra_sources=[("evil", bad)])
    assert rep.passed is False
    assert any(f.get("source") == "negative_shift" for f in rep.findings)
    assert "FAIL" in rep.summary()


def test_clean_extra_source_pass() -> None:
    good = "def f(s):\n    return s.shift(1)\n"
    rep = run_causal_preflight(extra_sources=[("ok", good)])
    assert rep.passed is True
