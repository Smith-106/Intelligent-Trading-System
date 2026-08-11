"""Tests for IAF correlation prune (research-only)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.research.iaf_prune import (
    IAF_FACTOR_NAMES,
    PruneConfig,
    prune_correlated_factors,
    prune_report_to_dict,
)


def test_drops_perfectly_correlated_column() -> None:
    n = 200
    rng = np.random.default_rng(0)
    x = rng.normal(size=n)
    df = pd.DataFrame(
        {
            "cci_20": x,
            "roc_12": x * 2 + 1e-9,  # perfect linear corr
            "mom_10": rng.normal(size=n),
        }
    )
    res = prune_correlated_factors(
        df,
        columns=["cci_20", "roc_12", "mom_10"],
        config=PruneConfig(threshold=0.7, method="pearson"),
    )
    assert "cci_20" in res.kept
    assert "roc_12" in res.dropped
    assert "mom_10" in res.kept
    assert res.research_only is True
    d = prune_report_to_dict(res)
    assert d["threshold"] == 0.7
    assert len(d["pairwise_dropped"]) >= 1


def test_empty_frame_fail_closed() -> None:
    with pytest.raises(ValueError, match="empty"):
        prune_correlated_factors(pd.DataFrame())


def test_iaf_names_nonempty() -> None:
    assert "cci_20" in IAF_FACTOR_NAMES
    assert len(IAF_FACTOR_NAMES) >= 10


def test_prefer_order() -> None:
    n = 100
    x = np.linspace(0, 1, n)
    df = pd.DataFrame({"a": x, "b": x})
    res = prune_correlated_factors(
        df,
        columns=["a", "b"],
        config=PruneConfig(threshold=0.5, method="pearson", prefer=("b",)),
    )
    assert res.kept[0] == "b"
    assert "a" in res.dropped
