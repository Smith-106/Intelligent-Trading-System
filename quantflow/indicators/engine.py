"""Indicator engine — batch compute classical indicators from pure pandas.

Factor surface (names in FACTOR_NAMES):
- Classical batch (batch_calculate / compute_all default): 21 core + extended
  (W18c supertrend/dema/stochRSI/KC/DC + volume ext + **IAF oscillators**).
- Wave names (6) remain listed for discovery but are NOT computed by batch_calculate;
  they require FactorRegistry + wave_count injection (see docs/research/w17-antifuture-and-factors.md).
- New factors must pass causal truncation tests (``indicators.causal``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import pandas as pd

from quantflow.indicators import momentum, oscillators, trend, volatility, volume
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
    # W19c volume extensions
    "session_vwap",
    "obv_slope",
    # W20b bar-level CVD proxy (not trade-tape CVD)
    "cvd_proxy",
    # IAF anti-overfit pack — orthogonal oscillators / vol surface
    "cci_20",
    "roc_12",
    "mom_10",
    "aroon_up",
    "aroon_down",
    "aroon_osc",
    "cmf_20",
    "realized_vol_20",
    "bb_width_20",
    "percent_b_20",
    "trix_15",
    "tsi",
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

        # W19c / W20b volume extensions
        ts = result["timestamp"] if "timestamp" in result.columns else None
        result["session_vwap"] = volume.session_vwap(high, low, close, vol, ts)
        result["obv_slope"] = volume.obv_slope(close, vol, 10)
        result["cvd_proxy"] = volume.cvd_proxy(close, vol)

        # IAF orthogonal oscillators (diversify factor surface; causal windows)
        result["cci_20"] = oscillators.cci(high, low, close, 20)
        result["roc_12"] = oscillators.roc(close, 12)
        result["mom_10"] = oscillators.momentum(close, 10)
        aroon_df = oscillators.aroon(high, low, 25)
        for col in aroon_df.columns:
            result[col] = aroon_df[col]
        result["cmf_20"] = oscillators.cmf(high, low, close, vol, 20)
        result["realized_vol_20"] = oscillators.realized_vol(close, 20)
        result["bb_width_20"] = oscillators.bb_width(close, 20)
        result["percent_b_20"] = oscillators.percent_b(close, 20)
        result["trix_15"] = oscillators.trix(close, 15)
        result["tsi"] = oscillators.tsi(close)

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

        # REV-009/S3: declarative spec table — (columns, builder). Each entry
        # computes its source frame once when any of its columns is requested.
        specs: tuple[tuple[frozenset[str], Callable[[], dict[str, pd.Series]]], ...] = (
            (frozenset({"sma_20"}), lambda: {"sma_20": trend.sma(close, 20)}),
            (frozenset({"sma_50"}), lambda: {"sma_50": trend.sma(close, 50)}),
            (frozenset({"ema_12"}), lambda: {"ema_12": trend.ema(close, 12)}),
            (frozenset({"ema_26"}), lambda: {"ema_26": trend.ema(close, 26)}),
            (
                frozenset({"macd", "macd_signal", "macd_histogram"}),
                lambda: {c: v for c, v in trend.macd(close).items()},
            ),
            (frozenset({"rsi_14"}), lambda: {"rsi_14": momentum.rsi(close, 14)}),
            (
                frozenset({"stoch_k", "stoch_d"}),
                lambda: {c: v for c, v in momentum.stochastic(high, low, close).items()},
            ),
            (
                frozenset({"williams_r_14"}),
                lambda: {"williams_r_14": momentum.williams_r(high, low, close, 14)},
            ),
            (frozenset({"atr_14"}), lambda: {"atr_14": volatility.atr(high, low, close, 14)}),
            (
                frozenset({"bb_upper", "bb_middle", "bb_lower"}),
                lambda: {c: v for c, v in volatility.bollinger_bands(close, 20, 2.0).items()},
            ),
            (frozenset({"adx_14"}), lambda: {"adx_14": trend.adx(high, low, close, 14)}),
            (frozenset({"obv"}), lambda: {"obv": volume.obv(close, vol)}),
            (frozenset({"vwap"}), lambda: {"vwap": volume.vwap(high, low, close, vol)}),
            (
                frozenset({"mfi_14"}),
                lambda: {"mfi_14": volume.mfi(high, low, close, vol, 14)},
            ),
            (
                frozenset({"volume_sma_20"}),
                lambda: {"volume_sma_20": volume.volume_sma(vol, 20)},
            ),
            (
                frozenset({"volume_ratio"}),
                lambda: {"volume_ratio": volume.volume_ratio(vol, 20)},
            ),
            (frozenset({"dema_20"}), lambda: {"dema_20": trend.dema(close, 20)}),
            (
                frozenset({"supertrend", "supertrend_direction"}),
                lambda: {c: v for c, v in trend.supertrend(high, low, close).items()},
            ),
            (
                frozenset({"stochrsi_k", "stochrsi_d"}),
                lambda: {c: v for c, v in momentum.stochastic_rsi(close).items()},
            ),
            (
                frozenset({"kc_upper", "kc_middle", "kc_lower"}),
                lambda: {c: v for c, v in volatility.keltner_channel(high, low, close).items()},
            ),
            (
                frozenset({"dc_upper", "dc_middle", "dc_lower"}),
                lambda: {c: v for c, v in volatility.donchian_channel(high, low).items()},
            ),
            (
                frozenset({"session_vwap"}),
                lambda: {
                    "session_vwap": volume.session_vwap(
                        high,
                        low,
                        close,
                        vol,
                        result["timestamp"] if "timestamp" in result.columns else None,
                    )
                },
            ),
            (
                frozenset({"obv_slope"}),
                lambda: {"obv_slope": volume.obv_slope(close, vol, 10)},
            ),
            (frozenset({"cvd_proxy"}), lambda: {"cvd_proxy": volume.cvd_proxy(close, vol)}),
            (frozenset({"cci_20"}), lambda: {"cci_20": oscillators.cci(high, low, close, 20)}),
            (frozenset({"roc_12"}), lambda: {"roc_12": oscillators.roc(close, 12)}),
            (frozenset({"mom_10"}), lambda: {"mom_10": oscillators.momentum(close, 10)}),
            (
                frozenset({"aroon_up", "aroon_down", "aroon_osc"}),
                lambda: {c: v for c, v in oscillators.aroon(high, low, 25).items()},
            ),
            (
                frozenset({"cmf_20"}),
                lambda: {"cmf_20": oscillators.cmf(high, low, close, vol, 20)},
            ),
            (
                frozenset({"realized_vol_20"}),
                lambda: {"realized_vol_20": oscillators.realized_vol(close, 20)},
            ),
            (
                frozenset({"bb_width_20"}),
                lambda: {"bb_width_20": oscillators.bb_width(close, 20)},
            ),
            (
                frozenset({"percent_b_20"}),
                lambda: {"percent_b_20": oscillators.percent_b(close, 20)},
            ),
            (frozenset({"trix_15"}), lambda: {"trix_15": oscillators.trix(close, 15)}),
            (frozenset({"tsi"}), lambda: {"tsi": oscillators.tsi(close)}),
        )
        for columns, build in specs:
            hit = columns & requested
            if not hit:
                continue
            for col, series_or_df_val in build().items():
                if col in hit:
                    result[col] = series_or_df_val

        return result

    # Alias for backwards compatibility
    calculate = batch_calculate
