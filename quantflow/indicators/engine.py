"""Indicator engine — batch compute 21+ indicators from pure pandas implementations."""

from __future__ import annotations

import logging

import pandas as pd

from quantflow.indicators import momentum, trend, volatility, volume
from quantflow.indicators.base import registry
from quantflow.indicators.critical_level import CriticalLevelDetector
from quantflow.indicators.divergence import DivergenceDetector
from quantflow.indicators.fibonacci import FibonacciCalculator
from quantflow.indicators.wave_channel import WaveChannel
from quantflow.indicators.wave_identifier import WaveIdentifier
from quantflow.indicators.zigzag import ZigZagIndicator

logger = logging.getLogger(__name__)


def _register_wave_factors() -> None:
    """Register Elliott Wave factors with the global registry."""
    registry.register(ZigZagIndicator)
    registry.register(WaveIdentifier)
    registry.register(FibonacciCalculator)
    registry.register(CriticalLevelDetector)
    registry.register(WaveChannel)
    registry.register(DivergenceDetector)


_register_wave_factors()

# 27 factors: trend(7) + momentum(4) + volatility(5) + volume(5) + elliott_wave(6)
FACTOR_NAMES = [
    # Trend (7)
    "sma_20",
    "sma_50",
    "ema_12",
    "ema_26",
    "macd",
    "macd_signal",
    "macd_histogram",
    # Momentum (4)
    "rsi_14",
    "stoch_k",
    "stoch_d",
    "williams_r_14",
    # Volatility (5)
    "atr_14",
    "bb_upper",
    "bb_middle",
    "bb_lower",
    "adx_14",
    # Volume (5)
    "obv",
    "vwap",
    "mfi_14",
    "volume_sma_20",
    "volume_ratio",
    # Elliott Wave (6)
    "zigzag_pivots",
    "wave_count",
    "fibonacci_levels",
    "critical_levels",
    "wave_channel",
    "divergence",
]


class IndicatorEngine:
    """Compute all 21 core indicators on a DataFrame.

    Uses pure pandas/numpy implementations — no external TA library required.
    """

    def batch_calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute all standard indicators and append as columns.

        Expected input columns: open, high, low, close, volume
        """
        result = df.copy()

        if "close" not in result.columns:
            return result

        close = result["close"]
        high = result.get("high", close)
        low = result.get("low", close)
        vol = result.get("volume", pd.Series(1.0, index=result.index))

        # --- Trend (7 columns) ---
        result["sma_20"] = trend.sma(close, 20)
        result["sma_50"] = trend.sma(close, 50)
        result["ema_12"] = trend.ema(close, 12)
        result["ema_26"] = trend.ema(close, 26)

        macd_df = trend.macd(close)
        for col in macd_df.columns:
            result[col] = macd_df[col]

        # --- Momentum (4 columns) ---
        result["rsi_14"] = momentum.rsi(close, 14)

        stoch_df = momentum.stochastic(high, low, close)
        for col in stoch_df.columns:
            result[col] = stoch_df[col]

        result["williams_r_14"] = momentum.williams_r(high, low, close, 14)

        # --- Volatility (5 columns) ---
        result["atr_14"] = volatility.atr(high, low, close, 14)

        bb_df = volatility.bollinger_bands(close, 20, 2.0)
        for col in bb_df.columns:
            result[col] = bb_df[col]

        result["adx_14"] = trend.adx(high, low, close, 14)

        # --- Volume (5 columns) ---
        result["obv"] = volume.obv(close, vol)
        result["vwap"] = volume.vwap(high, low, close, vol)
        result["mfi_14"] = volume.mfi(high, low, close, vol, 14)
        result["volume_sma_20"] = volume.volume_sma(vol, 20)
        result["volume_ratio"] = volume.volume_ratio(vol, 20)

        return result

    def list_available(self) -> list[str]:
        """Return the list of all available factor names."""
        return FACTOR_NAMES[:]

    def compute_all(
        self, df: pd.DataFrame, indicator_names: list[str] | None = None
    ) -> pd.DataFrame:
        """Compute indicators, optionally filtering to a subset by name.

        Args:
            df: OHLCV DataFrame.
            indicator_names: If provided, only compute these indicators.
                If None, compute all 21 standard indicators.
        """
        result = self.batch_calculate(df)
        if indicator_names:
            keep = set(df.columns) | set(indicator_names)
            result = result[[c for c in result.columns if c in keep]]
        return result

    # Alias for backwards compatibility
    calculate = batch_calculate
