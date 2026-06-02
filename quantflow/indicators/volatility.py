"""Volatility indicators — ATR, Bollinger Bands, Keltner Channel (pure pandas)."""

from __future__ import annotations

import pandas as pd


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range."""
    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """True Range."""
    return pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)


def bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    """Bollinger Bands.

    Returns DataFrame with columns: bb_upper, bb_middle, bb_lower.
    """
    middle = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return pd.DataFrame(
        {
            "bb_upper": upper,
            "bb_middle": middle,
            "bb_lower": lower,
        }
    )


def keltner_channel(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    ema_period: int = 20,
    atr_period: int = 10,
    multiplier: float = 2.0,
) -> pd.DataFrame:
    """Keltner Channel.

    Returns DataFrame with columns: kc_upper, kc_middle, kc_lower.
    """
    middle = close.ewm(span=ema_period, adjust=False).mean()
    atr_val = atr(high, low, close, atr_period)
    upper = middle + multiplier * atr_val
    lower = middle - multiplier * atr_val
    return pd.DataFrame(
        {
            "kc_upper": upper,
            "kc_middle": middle,
            "kc_lower": lower,
        }
    )


def donchian_channel(high: pd.Series, low: pd.Series, period: int = 20) -> pd.DataFrame:
    """Donchian Channel.

    Returns DataFrame with columns: dc_upper, dc_middle, dc_lower.
    """
    upper = high.rolling(period).max()
    lower = low.rolling(period).min()
    middle = (upper + lower) / 2
    return pd.DataFrame(
        {
            "dc_upper": upper,
            "dc_middle": middle,
            "dc_lower": lower,
        }
    )
