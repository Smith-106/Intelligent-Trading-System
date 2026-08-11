"""TPSL barrier params → (entries, exits) for validation_gate.

IMPORTANT: vectorized close-path exits are an *approximation* of
``simulate_long_flat_tpsl`` (which uses high/low intrabar). Reports must
label execution_model=vectorized_adapter vs tpsl_simulator.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

from quantflow.strategy.research.tpsl import dual_ma_entries

SignalFn = Callable[..., tuple[pd.Series, pd.Series]]


def barrier_param_space(
    *,
    stop_loss_pcts: tuple[float, ...] = (0.03, 0.04, 0.05),
    min_rrs: tuple[float, ...] = (2.0, 2.5, 3.0),
    max_holds: tuple[int, ...] = (0, 168),
) -> dict[str, tuple[Any, ...]]:
    """Discrete barrier grid for gate optimize / CPCV param_space."""
    # Encode as parallel lists of (sl, tp, min_rr, max_hold) via separate keys
    # Gate optimizers expect independent axes — use sl + min_rr + max_hold; tp=sl*rr
    return {
        "stop_loss_pct": stop_loss_pcts,
        "min_rr": min_rrs,
        "max_holding_bars": max_holds,
    }


def _exits_from_barriers(
    close: pd.Series,
    entries: pd.Series,
    *,
    stop_loss_pct: float,
    take_profit_pct: float,
    max_holding_bars: int = 0,
) -> pd.Series:
    """Close-only long/flat barrier exits (vectorized approximation)."""
    c = close.astype(float)
    ent = entries.astype(bool)
    n = len(c)
    exits = pd.Series(False, index=close.index, dtype=bool)
    in_pos = False
    entry_px = 0.0
    entry_i = -1
    for i in range(n):
        if not in_pos and bool(ent.iloc[i]):
            in_pos = True
            entry_px = float(c.iloc[i])
            entry_i = i
            continue
        if in_pos:
            px = float(c.iloc[i])
            sl = entry_px * (1.0 - stop_loss_pct)
            tp = entry_px * (1.0 + take_profit_pct)
            hit = px <= sl or px >= tp
            if max_holding_bars > 0 and (i - entry_i) >= max_holding_bars:
                hit = True
            if hit:
                exits.iloc[i] = True
                in_pos = False
    return exits


def make_dual_ma_tpsl_signal_fn(
    *,
    fast: int = 96,
    slow: int = 400,
    default_sl: float = 0.04,
    default_min_rr: float = 2.5,
    default_max_hold: int = 0,
) -> SignalFn:
    """Return signal_fn(df, **params) -> (entries, exits) for validation_gate."""

    def signal_fn(
        data: pd.DataFrame,
        stop_loss_pct: float = default_sl,
        min_rr: float = default_min_rr,
        max_holding_bars: int = default_max_hold,
        take_profit_pct: float | None = None,
        **_kwargs: Any,
    ) -> tuple[pd.Series, pd.Series]:
        if "close" not in data.columns:
            raise ValueError("data must contain 'close'")
        close = data["close"]
        entries, _on = dual_ma_entries(close, fast=fast, slow=slow)
        sl = float(stop_loss_pct)
        rr = float(min_rr)
        tp = float(take_profit_pct) if take_profit_pct is not None else sl * rr
        if sl <= 0:
            # safe all-false
            z = pd.Series(False, index=close.index)
            return z, z
        exits = _exits_from_barriers(
            close,
            entries,
            stop_loss_pct=sl,
            take_profit_pct=tp,
            max_holding_bars=int(max_holding_bars),
        )
        return entries.astype(bool), exits.astype(bool)

    return signal_fn
