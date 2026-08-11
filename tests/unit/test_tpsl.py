"""Unit tests for TP/SL + min R:R research simulator."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.indicators.causal import assert_series_causal
from quantflow.strategy.research.tpsl import (
    TPSLConfig,
    dual_ma_entries,
    simulate_long_flat_tpsl,
    summarize_trades,
)


@pytest.fixture
def trend_df() -> pd.DataFrame:
    # synthetic: up then down
    up = np.linspace(100, 130, 100)
    down = np.linspace(130, 100, 100)
    close = np.concatenate([up, down])
    return pd.DataFrame(
        {
            "close": close,
            "high": close * 1.005,
            "low": close * 0.995,
        }
    )


def test_min_rr_auto_lifts_tp() -> None:
    cfg = TPSLConfig(stop_loss_pct=0.02, take_profit_pct=0.02, min_rr=2.0)
    sl, tp = cfg.resolved_pcts(None, 100.0)
    assert sl == pytest.approx(0.02)
    assert tp == pytest.approx(0.04)


def test_hits_take_profit(trend_df: pd.DataFrame) -> None:
    close = trend_df["close"]
    entries = pd.Series(False, index=close.index)
    entries.iloc[5] = True
    sig = pd.Series(True, index=close.index)
    cfg = TPSLConfig(stop_loss_pct=0.02, take_profit_pct=0.04, min_rr=2.0, fee=0.0, slip=0.0)
    _eq, trades, stats, _ = simulate_long_flat_tpsl(
        close, entries, high=trend_df["high"], low=trend_df["low"], signal_on=sig, cfg=cfg
    )
    assert stats.n_trades >= 1
    assert any(t.reason == "tp" for t in trades)


def test_hits_stop_loss() -> None:
    close = pd.Series(np.linspace(100, 80, 50))
    high = close * 1.001
    low = close * 0.999
    entries = pd.Series(False, index=close.index)
    entries.iloc[1] = True
    sig = pd.Series(True, index=close.index)
    cfg = TPSLConfig(stop_loss_pct=0.05, take_profit_pct=0.20, min_rr=2.0, fee=0.0, slip=0.0)
    _eq, trades, stats, _ = simulate_long_flat_tpsl(
        close, entries, high=high, low=low, signal_on=sig, cfg=cfg
    )
    assert stats.n_trades == 1
    assert trades[0].reason == "sl"


def test_dual_ma_entries_causal() -> None:
    np.random.seed(0)
    close = pd.Series(40000 * np.exp(np.cumsum(np.random.normal(0, 0.01, 500))))

    def ent_series(df: pd.DataFrame) -> pd.Series:
        e, _ = dual_ma_entries(df["close"], 20, 50)
        return e.astype(float)

    frame = pd.DataFrame({"close": close})
    assert_series_causal(ent_series, frame, min_prefix=80, name="dual_ma_entries")


def test_summarize_empty() -> None:
    s = summarize_trades([])
    assert s.n_trades == 0
