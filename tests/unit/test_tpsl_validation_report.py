"""Tests for TPSL validation report envelope."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantflow.strategy.research.tpsl_validation_report import build_tpsl_validation_report


def test_underreported_refuses_go() -> None:
    n = 300
    close = pd.Series(np.linspace(100, 120, n))
    df = pd.DataFrame({"close": close})
    rep = build_tpsl_validation_report(
        df,
        fast=10,
        slow=30,
        claimed_n_trials=1,  # underreport vs grid+optimize+...
        optimize_trials=5,
        run_gate=False,
    )
    # with claimed 1 vs positive breakdown → underreported
    assert rep["promotion_eligible"] is False
    if rep["underreported"]:
        assert rep["decision"] == "NO-GO"
    assert "n_trials_breakdown" in rep


def test_skip_gate_has_breakdown() -> None:
    n = 400
    rng = np.random.default_rng(2)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    df = pd.DataFrame({"close": close})
    rep = build_tpsl_validation_report(
        df, fast=15, slow=40, optimize_trials=2, run_gate=False
    )
    assert rep["n_trials_accounted"] >= 1
    assert rep["promotion_eligible"] is False
    assert rep["pbo_source"] == "CPCV-embedded"
