"""Tests for SpotPerpArbStrategy — s4 T-s4-04 (funding-rate symmetric prototype).

Synthetic-data validation only (real funding/OI coverage limited, analyze F7).
Covers: long/short entry conditions, OI confirmation gate, exit band,
mirror symmetry (spot leg = -perp leg), missing-column degradation, and
insufficient-history short-circuit.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantflow.strategy.templates.spot_perp_arb import SpotPerpArbStrategy


def _df(n: int = 60) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {
            "funding_rate": pd.Series(0.0, index=idx, dtype=float),
            "open_interest": pd.Series(1000.0 + np.arange(n) * 10.0, index=idx, dtype=float),
        },
        index=idx,
    )


def _with_oi_spike(df: pd.DataFrame, at: int = 30) -> pd.DataFrame:
    """Force |3-bar OI change| > 5% at ``at`` (OI drops at ``at-3``).

    pct_change(3) at index i compares OI[i] vs OI[i-3]; the drop must be
    applied at i-3 (index 27 for at=30) to affect the change at ``at``.
    """
    df = df.copy()
    df.loc[df.index[at - 3], "open_interest"] = df.loc[df.index[at - 3], "open_interest"] * 0.90
    return df


class TestSpotPerpArbEntry:
    def test_negative_funding_extreme_enters_long_perp(self) -> None:
        df = _with_oi_spike(_df())
        df.loc[df.index[30], "funding_rate"] = -0.002  # extreme negative
        strat = SpotPerpArbStrategy()
        entries, _ = strat.generate_signals(df)
        assert entries.iloc[30] == 1  # long perp

    def test_positive_funding_extreme_enters_short_perp(self) -> None:
        df = _with_oi_spike(_df())
        df.loc[df.index[30], "funding_rate"] = 0.002  # extreme positive
        strat = SpotPerpArbStrategy()
        entries, _ = strat.generate_signals(df)
        assert entries.iloc[30] == -1  # short perp

    def test_extreme_funding_without_oi_confirmation_blocks(self) -> None:
        # OI flat (no change) → no confirmation → no entry.
        df = _df()
        df["open_interest"] = 1000.0
        df.loc[df.index[30], "funding_rate"] = -0.002
        strat = SpotPerpArbStrategy()
        entries, _ = strat.generate_signals(df)
        assert entries.iloc[30] == 0

    def test_neutral_funding_no_entry(self) -> None:
        df = _df()
        strat = SpotPerpArbStrategy()
        entries, _ = strat.generate_signals(df)
        assert (entries == 0).all()


class TestSpotPerpArbExitAndSymmetry:
    def test_funding_back_to_neutral_triggers_exit(self) -> None:
        df = _with_oi_spike(_df())
        df.loc[df.index[30], "funding_rate"] = -0.002
        # Funding returns to neutral at index 40.
        df.loc[df.index[40], "funding_rate"] = 0.0001
        strat = SpotPerpArbStrategy()
        _, exits = strat.generate_signals(df)
        assert exits.iloc[40] == 1

    def test_spot_leg_is_mirror_of_perp(self) -> None:
        df = _with_oi_spike(_df())
        df.loc[df.index[30], "funding_rate"] = -0.002
        strat = SpotPerpArbStrategy()
        entries, _ = strat.generate_signals(df)
        spot = strat.spot_leg()
        assert (spot == -entries).all()
        assert spot.iloc[30] == -1  # long perp → short spot

    def test_direction_symmetry_by_construction(self) -> None:
        """Flipping the funding sign flips the entry direction exactly."""
        df1, df2 = _with_oi_spike(_df()), _with_oi_spike(_df())
        df1.loc[df1.index[30], "funding_rate"] = 0.002
        df2.loc[df2.index[30], "funding_rate"] = -0.002
        e1, _ = SpotPerpArbStrategy().generate_signals(df1)
        e2, _ = SpotPerpArbStrategy().generate_signals(df2)
        assert (e1 == -e2).all()

    def test_missing_columns_degrades_to_no_signal(self) -> None:
        df = pd.DataFrame({"close": np.linspace(100, 110, 60)})
        strat = SpotPerpArbStrategy()
        entries, exits = strat.generate_signals(df)
        assert (entries == 0).all()
        assert (exits == 0).all()

    def test_insufficient_history_short_circuits(self) -> None:
        df = _df(n=5)
        strat = SpotPerpArbStrategy()
        entries, exits = strat.generate_signals(df)
        assert (entries == 0).all()
        assert (exits == 0).all()

    def test_on_bar_is_noop_for_prototype(self) -> None:
        """Event-driven path intentionally deferred (analyze F7)."""
        from quantflow.strategy.base import StrategyContext

        strat = SpotPerpArbStrategy()
        ctx = StrategyContext()
        strat.on_bar(ctx, None)  # type: ignore[arg-type]
        assert ctx.flush_signals() == []
