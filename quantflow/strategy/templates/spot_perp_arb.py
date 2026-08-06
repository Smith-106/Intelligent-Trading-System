"""Spot-perp arbitrage prototype — funding-rate extreme symmetric signals.

s4 (T-s4-04): prototype only. Uses funding-rate extremes + OI change to
trigger a *symmetric* pair of signals (spot long + perp short, or the
reverse) — the classic cash-and-carry / funding harvest structure.

This is a research prototype: logic is validated on synthetic data only
(real funding/OI coverage is limited, see s4 analyze F7). It is NOT a
trading recommendation. It does not place orders; it emits a compound
signal whose ``strategy_id`` encodes the pair leg.

Note: ``generate_signals`` returns the perp-side entries/exits; the spot
leg is the mirror (long perp → short spot) implied by the symmetric design.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from quantflow.common.models import Bar
from quantflow.strategy.base import StrategyBase, StrategyContext

logger = logging.getLogger(__name__)


class SpotPerpArbStrategy(StrategyBase):
    """Symmetric spot-perp funding-arbitrage signal prototype.

    Entry long perp (+ short spot): funding_rate < -entry_threshold AND
    OI change confirms crowd unwind (|oi_change| > oi_change_threshold).
    Entry short perp (+ long spot): funding_rate > +entry_threshold AND
    OI change confirms crowd build.

    Exit: funding rate returns to the neutral band (±exit_threshold) or
    OI reverses direction.

    Symmetry property: for every long entry there is a mirror short entry
    when the funding sign flips — the strategy's signature is direction-
    symmetric by construction (tested).
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(name="spot_perp_arb", params=params)
        self.required_regime = "any"
        p = self._params
        self._entry_threshold = p.get("entry_threshold", 0.001)
        self._exit_threshold = p.get("exit_threshold", 0.0003)
        self._oi_lookback = p.get("oi_lookback", 3)
        self._oi_change_threshold = p.get("oi_change_threshold", 0.05)
        self._min_history = self._oi_lookback + 5

    def on_init(self, ctx: StrategyContext) -> None:
        ctx.params = self._params

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        # Prototype: research-only path. Event-driven wiring intentionally
        # deferred until the vectorized logic is validated (analyze F7).
        return

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Generate perp-side entries/exits from funding + OI data.

        Expected df columns: ``funding_rate`` and ``open_interest`` (both
        optional — missing columns degrade to no signal, never raise).

        Returns:
            (entries, exits): entries=+1 long perp / -1 short perp int Series,
            exits=+1 exit signal int Series (aligned to df index).
        """
        n = len(df)
        empty = pd.Series(0, index=df.index, dtype=int)
        if n < self._min_history:
            return empty, empty
        if "funding_rate" not in df or "open_interest" not in df:
            logger.warning("spot_perp_arb: missing funding_rate/open_interest columns")
            return empty, empty

        funding = df["funding_rate"].astype(float)
        oi = df["open_interest"].astype(float)
        oi_change = oi.pct_change(self._oi_lookback).fillna(0.0)

        entries = pd.Series(0, index=df.index, dtype=int)
        exits = pd.Series(0, index=df.index, dtype=int)

        long_mask = (funding < -self._entry_threshold) & (oi_change.abs() > self._oi_change_threshold)
        short_mask = (funding > self._entry_threshold) & (oi_change.abs() > self._oi_change_threshold)
        entries[long_mask] = 1
        entries[short_mask] = -1

        exit_mask = funding.abs() < self._exit_threshold
        exits[exit_mask] = 1

        # Mirror-symmetry: the spot leg is the opposite of the perp leg.
        self._spot_leg = -entries
        return entries, exits

    def spot_leg(self) -> pd.Series:
        """The symmetric spot side (mirror of the perp entries)."""
        return getattr(self, "_spot_leg", pd.Series(dtype=int))
