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
