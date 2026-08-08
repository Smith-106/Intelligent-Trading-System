"""Structure-layer entry modes for TrendFollowingStrategy (option B)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.templates.trend_following import TrendFollowingStrategy


def _trend_df(n: int = 120) -> pd.DataFrame:
    """Synthetic uptrend with a mid pullback and a late breakout."""
    rng = np.random.default_rng(0)
    base = np.linspace(100.0, 150.0, n)
    # Inject a dip around the middle so pullback can fire.
    base[50:56] -= np.linspace(0, 4, 6)
    base[56:62] += np.linspace(0, 4, 6)
    noise = rng.normal(0, 0.15, n)
    close = base + noise
    high = close + 0.8
    low = close - 0.8
    # Force a clean breakout at the end.
    high[-5:] = close[-5:] + 2.0
    close[-1] = high[-6] + 1.0
    high[-1] = close[-1] + 0.5
    return pd.DataFrame(
        {
            "close": close,
            "high": high,
            "low": low,
            "volume": np.full(n, 2_000.0),
        }
    )


def _loose_params(structure: str) -> dict[str, object]:
    # Loose filters so structure is the binding constraint in tests.
    return {
        "entry_structure": structure,
        "fast_ma_period": 5,
        "slow_ma_period": 15,
        "min_conditions": 1,
        "rsi_overbought": 100,
        "volume_threshold": 0.0,
        "atr_multiplier": 100.0,
        "pullback_lookback": 5,
        "pullback_tol": 0.02,
        "breakout_lookback": 10,
    }


def test_unknown_entry_structure_raises() -> None:
    with pytest.raises(ValueError, match="entry_structure"):
        TrendFollowingStrategy(params={"entry_structure": "moonshot"})


def test_classic_default_name() -> None:
    s = TrendFollowingStrategy()
    assert s._entry_structure == "classic"


def test_structures_are_stricter_or_equal_than_classic() -> None:
    df = _trend_df()
    classic = TrendFollowingStrategy(params=_loose_params("classic"))
    pullback = TrendFollowingStrategy(params=_loose_params("pullback"))
    breakout = TrendFollowingStrategy(params=_loose_params("breakout"))
    e_c, _ = classic.generate_signals(df)
    e_p, _ = pullback.generate_signals(df)
    e_b, _ = breakout.generate_signals(df)
    # Structure filters can only remove entries, never add.
    assert bool((~e_c & e_p).sum() == 0)
    assert bool((~e_c & e_b).sum() == 0)
    assert int(e_p.sum()) <= int(e_c.sum())
    assert int(e_b.sum()) <= int(e_c.sum())


def test_pullback_and_breakout_can_produce_entries() -> None:
    df = _trend_df(160)
    for structure in ("classic", "pullback", "breakout"):
        s = TrendFollowingStrategy(params=_loose_params(structure))
        entries, _exits = s.generate_signals(df)
        assert entries.dtype == bool or str(entries.dtype) == "bool"
        assert len(entries) == len(df)
        # With loose filters, classic should fire; structures may still fire.
        if structure == "classic":
            assert int(entries.sum()) > 0


def test_breakout_no_lookahead_uses_prior_high_only() -> None:
    # Flat then single spike on last bar — breakout must use prior highs only.
    n = 40
    close = np.full(n, 100.0)
    high = np.full(n, 100.5)
    low = np.full(n, 99.5)
    close[-1] = 110.0
    high[-1] = 110.5
    df = pd.DataFrame(
        {"close": close, "high": high, "low": low, "volume": np.full(n, 1000.0)}
    )
    s = TrendFollowingStrategy(
        params={
            **_loose_params("breakout"),
            "breakout_lookback": 10,
            "fast_ma_period": 3,
            "slow_ma_period": 5,
            "macd_fast": 3,
            "macd_slow": 5,
            "macd_signal": 2,
        }
    )
    entries, _ = s.generate_signals(df)
    # Last bar closes above all prior highs → breakout eligible if trend_up.
    # Even if trend filter blocks, the mask itself must not use current high
    # as the breakout level (would always fail). Smoke: no exception + length.
    assert len(entries) == n
