"""Trend indicators — SMA, EMA, DEMA, MACD (pure pandas implementation)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int = 20) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int = 20) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def dema(series: pd.Series, period: int = 20) -> pd.Series:
    """Double Exponential Moving Average."""
    e1 = ema(series, period)
    e2 = ema(e1, period)
    return 2 * e1 - e2


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD indicator.

    Returns DataFrame with columns: macd, signal, histogram.
    """
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return pd.DataFrame({
        "macd": macd_line,
        "macd_signal": signal_line,
        "macd_histogram": histogram,
    })


def supertrend(high: pd.Series, low: pd.Series, close: pd.Series,
               period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """Supertrend indicator.

    Returns DataFrame with columns: supertrend, direction.
    """
    # ATR calculation
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()

    hl2 = (high + low) / 2
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    # Supertrend logic
    st = pd.Series(np.nan, index=close.index)
    direction = pd.Series(1, index=close.index)  # 1=up, -1=down

    for i in range(period, len(close)):
        if close.iloc[i] > upper_band.iloc[i - 1]:
            direction.iloc[i] = 1
        elif close.iloc[i] < lower_band.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]

        if direction.iloc[i] == 1:
            st.iloc[i] = max(lower_band.iloc[i], st.iloc[i - 1]) if not np.isnan(st.iloc[i - 1]) else lower_band.iloc[i]
        else:
            st.iloc[i] = min(upper_band.iloc[i], st.iloc[i - 1]) if not np.isnan(st.iloc[i - 1]) else upper_band.iloc[i]

    return pd.DataFrame({
        "supertrend": st,
        "supertrend_direction": direction,
    })


def adx(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> pd.Series:
    """Average Directional Index — trend strength regardless of direction.

    Values > 25 indicate a trending market; < 20 indicate ranging.
    """
    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    atr_val = tr.rolling(period).mean()
    plus_di = 100 * plus_dm.rolling(period).mean() / atr_val.replace(0, 1e-10)
    minus_di = 100 * minus_dm.rolling(period).mean() / atr_val.replace(0, 1e-10)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-10)
    return dx.rolling(period).mean()
