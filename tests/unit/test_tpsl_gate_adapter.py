"""Tests for TPSL → signal_fn adapter."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantflow.strategy.research.tpsl_gate_adapter import (
    barrier_param_space,
    make_dual_ma_tpsl_signal_fn,
)


def test_signal_fn_lengths() -> None:
    n = 500
    rng = np.random.default_rng(1)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    df = pd.DataFrame({"close": close})
    fn = make_dual_ma_tpsl_signal_fn(fast=20, slow=50)
    ent, ex = fn(df, stop_loss_pct=0.04, min_rr=2.5)
    assert len(ent) == n and len(ex) == n
    assert ent.dtype == bool or str(ent.dtype) == "bool"
    assert not ent.isna().any()


def test_param_space_nonempty() -> None:
    space = barrier_param_space()
    assert "stop_loss_pct" in space and "min_rr" in space
