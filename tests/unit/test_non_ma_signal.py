"""Tests for NonMaSignalStrategy families."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.templates.non_ma_signal import FAMILIES, NonMaSignalStrategy


def _df(n: int = 100) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    close = np.cumsum(rng.normal(0.05, 1.0, n)) + 100
    high = close + rng.uniform(0.2, 1.0, n)
    low = close - rng.uniform(0.2, 1.0, n)
    volume = rng.uniform(800, 2000, n)
    # Force a late breakout + volume spike for donchian/volume families.
    close[-1] = high[-20:-1].max() + 2
    high[-1] = close[-1] + 0.5
    volume[-1] = volume[-20:].mean() * 3
    return pd.DataFrame({"close": close, "high": high, "low": low, "volume": volume})


def test_unknown_family_raises() -> None:
    with pytest.raises(ValueError, match="signal_family"):
        NonMaSignalStrategy(params={"signal_family": "macd"})


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_generate_signals_shape(family: str) -> None:
    s = NonMaSignalStrategy(params={"signal_family": family})
    df = _df()
    entries, exits = s.generate_signals(df)
    assert len(entries) == len(df)
    assert len(exits) == len(df)
    assert entries.dtype == bool or str(entries.dtype) == "bool"


def test_donchian_can_enter_on_breakout() -> None:
    s = NonMaSignalStrategy(
        params={"signal_family": "donchian", "channel_period": 10, "exit_period": 5}
    )
    df = _df(80)
    entries, _ = s.generate_signals(df)
    # With forced terminal breakout, at least one entry is expected.
    assert int(entries.sum()) >= 1


def test_registered_in_paper_replay() -> None:
    from quantflow.strategy.research.paper_replay import STRATEGIES, build_session

    assert "non_ma_signal" in STRATEGIES
    session = build_session("non_ma_signal", params={"signal_family": "volume_roc"})
    assert session._strategies[0].name == "non_ma_signal"
