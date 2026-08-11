"""Tests for IAF prune → CPCV research pipeline."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd

from quantflow.strategy.research.iaf_prune import IAF_FACTOR_NAMES
from quantflow.strategy.research.iaf_prune_cpcv import (
    research_signal_from_kept_factors,
    run_iaf_prune_cpcv,
)


def test_research_signal_is_lagged() -> None:
    n = 200
    rng = np.random.default_rng(1)
    frame = pd.DataFrame({name: rng.normal(size=n) for name in IAF_FACTOR_NAMES[:4]})
    ent, _ex = research_signal_from_kept_factors(frame, list(frame.columns), lag=1)
    assert len(ent) == n
    assert not ent.iloc[0]  # first bar after lag should not fire from raw t0


def test_run_iaf_prune_cpcv_never_binds(monkeypatch) -> None:
    n = 800
    rng = np.random.default_rng(2)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    df = pd.DataFrame(
        {
            "close": close,
            "high": close * 1.001,
            "low": close * 0.999,
            "open": close,
            "volume": rng.uniform(1, 10, n),
        }
    )
    # mock factor frame to avoid full indicator engine dependency flakiness
    fake = pd.DataFrame({name: rng.normal(size=n) for name in IAF_FACTOR_NAMES})

    with patch(
        "quantflow.strategy.research.iaf_prune_cpcv._compute_iaf_frame",
        return_value=fake,
    ):
        with patch(
            "quantflow.strategy.research.iaf_prune_cpcv.cpcv_backtest",
            return_value={"pbo": 0.2, "passed": True, "n_paths": 15},
        ):
            rep = run_iaf_prune_cpcv(df, cpcv_groups=4, cpcv_test_groups=1)

    assert rep["hard_bind_entry"] is False
    assert rep["promotion_eligible"] is False
    assert rep["research_only"] is True
    assert "kept" in rep["prune"]
    assert rep["cpcv"]["decision"] in {"PASS", "NO-GO"}
