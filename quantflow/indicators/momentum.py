"""Momentum indicators — RSI, Stochastic, Williams %R (pure pandas)."""

from __future__ import annotations

import pandas as pd


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder smoothing)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    # Wilder smoothing (exponential with alpha=1/period)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def stochastic_rsi(series: pd.Series, rsi_period: int = 14,
                   stoch_period: int = 14, k_smooth: int = 3,
                   d_smooth: int = 3) -> pd.DataFrame:
    """Stochastic RSI.

    Returns DataFrame with columns: stochrsi_k, stochrsi_d.
    """
    rsi_val = rsi(series, rsi_period)
    rsi_min = rsi_val.rolling(stoch_period).min()
    rsi_max = rsi_val.rolling(stoch_period).max()
    stoch = (rsi_val - rsi_min) / (rsi_max - rsi_min).replace(0, 1e-10) * 100
    k = stoch.rolling(k_smooth).mean()
    d = k.rolling(d_smooth).mean()
    return pd.DataFrame({"stochrsi_k": k, "stochrsi_d": d})


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
               k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
    """Stochastic Oscillator.

    Returns DataFrame with columns: stoch_k, stoch_d.
    """
    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    k = (close - lowest_low) / (highest_high - lowest_low).replace(0, 1e-10) * 100
    d = k.rolling(d_period).mean()
    return pd.DataFrame({"stoch_k": k, "stoch_d": d})


def williams_r(high: pd.Series, low: pd.Series, close: pd.Series,
               period: int = 14) -> pd.Series:
    """Williams %R."""
    highest = high.rolling(period).max()
    lowest = low.rolling(period).min()
    return (highest - close) / (highest - lowest).replace(0, 1e-10) * -100
