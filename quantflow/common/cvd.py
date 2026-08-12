"""CVD helpers shared by L1 data and L2 indicators (layer-safe).

These pure Series transforms must not live only under ``indicators/`` —
``quantflow/data`` (L1) needs them without importing L2 (ISS-002).
L2 ``indicators.volume`` re-exports the same symbols for research DX.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def cvd_from_trades(
    prices: pd.Series,
    amounts: pd.Series,
    sides: pd.Series,
) -> pd.Series:
    """True-ish CVD from trade tape (W21c).

    ``sides`` values: buy/long/b/+1 → +amount; sell/short/s/-1 → -amount.
    Returns cumulative sum aligned to the trade index. Empty inputs → empty Series.
    """
    del prices  # prices reserved for future aggressor/mid refinements
    if len(amounts) == 0:
        return pd.Series(dtype=float)
    side_num = sides.map(_side_to_sign).astype(float)
    delta = amounts.astype(float) * side_num
    return delta.cumsum()


def _side_to_sign(side: object) -> float:
    s = str(side or "").strip().lower()
    if s in ("buy", "b", "long", "1", "+1", "bid"):
        return 1.0
    if s in ("sell", "s", "short", "-1", "ask"):
        return -1.0
    try:
        v = float(s)
        return 1.0 if v > 0 else (-1.0 if v < 0 else 0.0)
    except (TypeError, ValueError):
        return 0.0


def cvd_proxy(close: pd.Series, volume: pd.Series) -> pd.Series:
    """Bar-level Cumulative Volume Delta **proxy** (W20b).

    Without trade-level aggressor flags, approximate delta as:
    ``sign(close_t - close_{t-1}) * volume_t``, then cumulative sum.
    This is **not** true exchange CVD; do not claim trade-tape fidelity.
    First bar contributes 0 (no prior close).
    """
    direction = np.sign(close.diff())
    direction = direction.fillna(0.0)
    direction.iloc[0] = 0.0
    delta = volume.astype(float) * direction
    return delta.cumsum()
