"""Indicator engine — batch compute classical indicators from pure pandas.

W18c surface (names in FACTOR_NAMES):
- Classical batch (batch_calculate / compute_all default): 21 core + 5 dormant
  extended factors that are now wired (supertrend/dema/stochRSI/keltner/donchian).
- Wave names (6) remain listed for discovery but are NOT computed by batch_calculate;
  they require FactorRegistry + wave_count injection (see docs/research/w17-antifuture-and-factors.md).
"""

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

# Exposed names (W18c): classical batch columns + wave discovery names.
# batch_calculate computes CLASSICAL only (21 core + 5 extended).
# Wave 6 are registry-only (not batch-computed).
CLASSICAL_CORE_NAMES = [
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
]

# Previously implemented but unwired (W18c expose pack)
CLASSICAL_EXTENDED_NAMES = [
    "dema_20",
    "supertrend",
    "supertrend_direction",
    "stochrsi_k",
    "stochrsi_d",
    "kc_upper",
    "kc_middle",
    "kc_lower",
    "dc_upper",
    "dc_middle",
    "dc_lower",
]

WAVE_FACTOR_NAMES = [
    "zigzag_pivots",
    "wave_count",
    "fibonacci_levels",
    "critical_levels",
    "wave_channel",
    "divergence",
]

FACTOR_NAMES = CLASSICAL_CORE_NAMES + CLASSICAL_EXTENDED_NAMES + WAVE_FACTOR_NAMES


class IndicatorEngine:
    """Compute classical indicators on a DataFrame.

    Uses pure pandas/numpy implementations — no external TA library required.
    Default batch = 21 core + W18c extended (supertrend/dema/stochRSI/KC/DC).
    Wave factors are not computed here.
    """

    def batch_calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute classical (core + extended) indicators and append as columns.

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

        # --- W18c extended classical (previously dormant) ---
        result["dema_20"] = trend.dema(close, 20)
        st_df = trend.supertrend(high, low, close)
        for col in st_df.columns:
            result[col] = st_df[col]
        srsi_df = momentum.stochastic_rsi(close)
        for col in srsi_df.columns:
            result[col] = srsi_df[col]
        kc_df = volatility.keltner_channel(high, low, close)
        for col in kc_df.columns:
            result[col] = kc_df[col]
        dc_df = volatility.donchian_channel(high, low)
        for col in dc_df.columns:
            result[col] = dc_df[col]

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
        if not indicator_names:
            return self.batch_calculate(df)

        result = df.copy()
        if "close" not in result.columns:
            return result

        requested = set(indicator_names)
        close = result["close"]
        high = result.get("high", close)
        low = result.get("low", close)
        vol = result.get("volume", pd.Series(1.0, index=result.index))

        if "sma_20" in requested:
            result["sma_20"] = trend.sma(close, 20)
        if "sma_50" in requested:
            result["sma_50"] = trend.sma(close, 50)
        if "ema_12" in requested:
            result["ema_12"] = trend.ema(close, 12)
        if "ema_26" in requested:
            result["ema_26"] = trend.ema(close, 26)

        macd_columns = {"macd", "macd_signal", "macd_histogram"}
        if requested & macd_columns:
            macd_df = trend.macd(close)
            for col in macd_columns & requested:
                result[col] = macd_df[col]

        if "rsi_14" in requested:
            result["rsi_14"] = momentum.rsi(close, 14)

        stoch_columns = {"stoch_k", "stoch_d"}
        if requested & stoch_columns:
            stoch_df = momentum.stochastic(high, low, close)
            for col in stoch_columns & requested:
                result[col] = stoch_df[col]

        if "williams_r_14" in requested:
            result["williams_r_14"] = momentum.williams_r(high, low, close, 14)
        if "atr_14" in requested:
            result["atr_14"] = volatility.atr(high, low, close, 14)

        bb_columns = {"bb_upper", "bb_middle", "bb_lower"}
        if requested & bb_columns:
            bb_df = volatility.bollinger_bands(close, 20, 2.0)
            for col in bb_columns & requested:
                result[col] = bb_df[col]

        if "adx_14" in requested:
            result["adx_14"] = trend.adx(high, low, close, 14)
        if "obv" in requested:
            result["obv"] = volume.obv(close, vol)
        if "vwap" in requested:
            result["vwap"] = volume.vwap(high, low, close, vol)
        if "mfi_14" in requested:
            result["mfi_14"] = volume.mfi(high, low, close, vol, 14)
        if "volume_sma_20" in requested:
            result["volume_sma_20"] = volume.volume_sma(vol, 20)
        if "volume_ratio" in requested:
            result["volume_ratio"] = volume.volume_ratio(vol, 20)

        # W18c extended classical
        if "dema_20" in requested:
            result["dema_20"] = trend.dema(close, 20)

        st_columns = {"supertrend", "supertrend_direction"}
        if requested & st_columns:
            st_df = trend.supertrend(high, low, close)
            for col in st_columns & requested:
                result[col] = st_df[col]

        srsi_columns = {"stochrsi_k", "stochrsi_d"}
        if requested & srsi_columns:
            srsi_df = momentum.stochastic_rsi(close)
            for col in srsi_columns & requested:
                result[col] = srsi_df[col]

        kc_columns = {"kc_upper", "kc_middle", "kc_lower"}
        if requested & kc_columns:
            kc_df = volatility.keltner_channel(high, low, close)
            for col in kc_columns & requested:
                result[col] = kc_df[col]

        dc_columns = {"dc_upper", "dc_middle", "dc_lower"}
        if requested & dc_columns:
            dc_df = volatility.donchian_channel(high, low)
            for col in dc_columns & requested:
                result[col] = dc_df[col]

        return result

    # Alias for backwards compatibility
    calculate = batch_calculate
