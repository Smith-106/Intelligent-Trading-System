"""Additional oscillators / breadth-style factors (pure pandas, causal).

Orthogonal to the core RSI/MACD set to diversify research surfaces without
forcing high-parameter curve fits. All windows are trailing-only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantflow.indicators.trend import ema


def cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    """Commodity Channel Index (Lambert)."""
    tp = (high.astype(float) + low.astype(float) + close.astype(float)) / 3.0
    sma = tp.rolling(period, min_periods=period).mean()
    mad = tp.rolling(period, min_periods=period).apply(
        lambda x: np.mean(np.abs(x - np.mean(x))), raw=True
    )
    return (tp - sma) / (0.015 * mad.replace(0, np.nan))


def roc(series: pd.Series, period: int = 12) -> pd.Series:
    """Rate of Change in percent: 100 * (close / close.shift(n) - 1)."""
    s = series.astype(float)
    return 100.0 * (s / s.shift(period) - 1.0)


def momentum(series: pd.Series, period: int = 10) -> pd.Series:
    """Raw momentum: close - close.shift(n)."""
    s = series.astype(float)
    return s - s.shift(period)


def aroon(high: pd.Series, low: pd.Series, period: int = 25) -> pd.DataFrame:
    """Aroon Up / Down / Oscillator (0-100 scale).

    Window length is ``period + 1`` bars so the lookback spans ``period``
    intervals (standard Aroon definition).
    """
    h = high.astype(float)
    lo = low.astype(float)

    def _since_high(x: np.ndarray) -> float:
        # periods since highest high within window (0 = today is high)
        return 100.0 * (period - (len(x) - 1 - int(np.argmax(x)))) / period

    def _since_low(x: np.ndarray) -> float:
        return 100.0 * (period - (len(x) - 1 - int(np.argmin(x)))) / period

    win = period + 1
    up = h.rolling(win, min_periods=win).apply(_since_high, raw=True)
    down = lo.rolling(win, min_periods=win).apply(_since_low, raw=True)
    return pd.DataFrame(
        {
            "aroon_up": up,
            "aroon_down": down,
            "aroon_osc": up - down,
        }
    )


def cmf(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    period: int = 20,
) -> pd.Series:
    """Chaikin Money Flow."""
    h = high.astype(float)
    lo = low.astype(float)
    c = close.astype(float)
    v = volume.astype(float)
    hl = (h - lo).replace(0, np.nan)
    mfm = ((c - lo) - (h - c)) / hl
    mfm = mfm.fillna(0.0)
    mfv = mfm * v
    return mfv.rolling(period, min_periods=period).sum() / v.rolling(
        period, min_periods=period
    ).sum().replace(0, np.nan)


def realized_vol(close: pd.Series, period: int = 20, bars_per_year: float = 8760.0) -> pd.Series:
    """Trailing realized volatility (annualized) from log returns."""
    r = np.log(close.astype(float) / close.astype(float).shift(1))
    return r.rolling(period, min_periods=period).std() * np.sqrt(bars_per_year)


def bb_width(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.Series:
    """Bollinger Band width: (upper - lower) / middle."""
    mid = series.astype(float).rolling(period, min_periods=period).mean()
    sd = series.astype(float).rolling(period, min_periods=period).std()
    upper = mid + std_dev * sd
    lower = mid - std_dev * sd
    return (upper - lower) / mid.replace(0, np.nan)


def percent_b(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.Series:
    """Bollinger %B: (close - lower) / (upper - lower)."""
    mid = series.astype(float).rolling(period, min_periods=period).mean()
    sd = series.astype(float).rolling(period, min_periods=period).std()
    upper = mid + std_dev * sd
    lower = mid - std_dev * sd
    return (series.astype(float) - lower) / (upper - lower).replace(0, np.nan)


def trix(series: pd.Series, period: int = 15) -> pd.Series:
    """TRIX: rate of change of triple EMA (percent)."""
    e1 = ema(series.astype(float), period)
    e2 = ema(e1, period)
    e3 = ema(e2, period)
    return 100.0 * (e3 / e3.shift(1) - 1.0)


def tsi(series: pd.Series, long_period: int = 25, short_period: int = 13) -> pd.Series:
    """True Strength Index (double-smoothed momentum)."""
    m = series.astype(float).diff()
    abs_m = m.abs()
    # double EMA smoothing
    m1 = m.ewm(span=long_period, adjust=False).mean()
    m2 = m1.ewm(span=short_period, adjust=False).mean()
    a1 = abs_m.ewm(span=long_period, adjust=False).mean()
    a2 = a1.ewm(span=short_period, adjust=False).mean()
    return 100.0 * m2 / a2.replace(0, np.nan)
