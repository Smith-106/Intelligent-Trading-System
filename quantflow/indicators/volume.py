"""Volume indicators — OBV, VWAP, MFI, Volume SMA (pure pandas)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    direction = np.sign(close.diff())
    direction.iloc[0] = 0
    return (volume * direction).cumsum()


def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    """Volume Weighted Average Price (cumulative daily)."""
    typical_price = (high + low + close) / 3
    cum_tp_vol = (typical_price * volume).cumsum()
    cum_vol = volume.cumsum()
    return cum_tp_vol / cum_vol.replace(0, 1e-10)


def mfi(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int = 14
) -> pd.Series:
    """Money Flow Index."""
    typical_price = (high + low + close) / 3
    raw_money_flow = typical_price * volume

    positive_flow = raw_money_flow.where(typical_price > typical_price.shift(1), 0.0)
    negative_flow = raw_money_flow.where(typical_price < typical_price.shift(1), 0.0)

    pos_sum = positive_flow.rolling(period).sum()
    neg_sum = negative_flow.rolling(period).sum()

    mfi_val = 100 - (100 / (1 + pos_sum / neg_sum.replace(0, 1e-10)))
    return mfi_val


def volume_sma(volume: pd.Series, period: int = 20) -> pd.Series:
    """Volume Simple Moving Average."""
    return volume.rolling(period).mean()


def volume_ratio(volume: pd.Series, period: int = 20) -> pd.Series:
    """Volume Ratio (current / SMA)."""
    avg = volume_sma(volume, period)
    return volume / avg.replace(0, 1e-10)


def session_vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    timestamps: pd.Series | None = None,
) -> pd.Series:
    """Session VWAP reset on UTC calendar day (W19c).

    When ``timestamps`` (ms epoch) is provided, cumulative TP*V / V resets at
    each UTC day boundary. Without timestamps, falls back to full-series
    cumulative VWAP (same as :func:`vwap`).
    """
    typical_price = (high + low + close) / 3.0
    tp_vol = typical_price * volume
    if timestamps is None:
        cum_tp = tp_vol.cumsum()
        cum_v = volume.cumsum()
        return cum_tp / cum_v.replace(0, 1e-10)

    day = (pd.to_numeric(timestamps, errors="coerce").astype("int64") // 86_400_000).astype("int64")
    # groupby cumsum is causal within each day (no future leakage across days)
    cum_tp = tp_vol.groupby(day).cumsum()
    cum_v = volume.groupby(day).cumsum()
    return cum_tp / cum_v.replace(0, 1e-10)


def obv_slope(close: pd.Series, volume: pd.Series, period: int = 10) -> pd.Series:
    """Rolling slope of OBV over ``period`` bars (W19c).

    ``obv_t - obv_{t-period}`` — simple causal difference, not a regression fit.
    """
    line = obv(close, volume)
    return line.diff(period)


# CVD helpers live in quantflow.common.cvd so L1 data can use them without
# importing L2 indicators (ISS-002). Re-export here for research DX.
from quantflow.common.cvd import cvd_from_trades, cvd_proxy  # noqa: E402

__all__ = [
    "cvd_from_trades",
    "cvd_proxy",
    "mfi",
    "obv",
    "obv_slope",
    "session_vwap",
    "volume_ratio",
    "volume_sma",
    "vwap",
]
