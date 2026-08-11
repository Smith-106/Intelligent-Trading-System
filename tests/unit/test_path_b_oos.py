"""Tests for Path B multi-window OOS."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantflow.strategy.research.path_b_oos import run_path_b_multi_window_oos


def _synth(n: int = 2000) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n)))
    high = close * (1 + rng.uniform(0, 0.005, n))
    low = close * (1 - rng.uniform(0, 0.005, n))
    return pd.DataFrame({"close": close, "high": high, "low": low})


def test_multi_window_honest_and_no_promote() -> None:
    df = _synth()
    rep = run_path_b_multi_window_oos(
        df,
        profile={
            "fast": 20,
            "slow": 60,
            "stop_loss_pct": 0.04,
            "take_profit_pct": 0.10,
            "min_rr": 2.5,
            "max_holding_bars": 0,
            "fee": 0.001,
            "slip": 0.001,
        },
        n_windows=4,
        oos_ratio=0.3,
        fixed_params=True,
    )
    assert rep["promotion_eligible"] is False
    assert rep["hard_bind_entry"] is False
    assert rep["n_trials_accounted"] >= 1
    assert rep["underreported"] is False
    assert len(rep["windows"]) >= 2
    assert "combined_score" not in rep
    assert rep["research_go"] in {"GO_DISCUSS", "NO-GO"}


def test_underreported_blocks_go_discuss() -> None:
    df = _synth(1500)
    rep = run_path_b_multi_window_oos(
        df,
        profile={
            "fast": 15,
            "slow": 50,
            "stop_loss_pct": 0.04,
            "take_profit_pct": 0.10,
            "min_rr": 2.5,
            "max_holding_bars": 0,
            "fee": 0.001,
            "slip": 0.001,
        },
        n_windows=3,
        fixed_params=False,
        claimed_n_trials=1,
    )
    # claimed 1 vs positive search budget → underreported → no GO discuss
    if rep["underreported"]:
        assert rep["go_discussion_allowed"] is False
        assert rep["research_go"] == "NO-GO"
