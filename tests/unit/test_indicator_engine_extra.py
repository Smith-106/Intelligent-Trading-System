"""Tests for indicators/engine.py uncovered paths — compute_all selective mode."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantflow.indicators.engine import IndicatorEngine


def _make_ohlcv(n: int = 60) -> pd.DataFrame:
    """Create a simple OHLCV DataFrame for testing."""
    rng = np.random.default_rng(42)
    close = pd.Series(100.0 + rng.normal(0, 2, n).cumsum())
    close = close.clip(lower=10)
    return pd.DataFrame(
        {
            "open": close + rng.normal(0, 0.5, n),
            "high": close + rng.uniform(0.5, 3, n),
            "low": close - rng.uniform(0.5, 3, n),
            "close": close,
            "volume": rng.uniform(100, 1000, n),
        }
    )


class TestIndicatorEngineComputeAllSelective:
    def test_compute_all_with_none_indicator_names(self):
        """Line 143: indicator_names=None → batch_calculate."""
        engine = IndicatorEngine()
        df = _make_ohlcv()
        result = engine.compute_all(df, indicator_names=None)
        assert "rsi_14" in result.columns  # batch_calculate adds standard columns

    def test_compute_all_with_empty_indicator_names(self):
        """Line 143: indicator_names=[] → batch_calculate (falsy)."""
        engine = IndicatorEngine()
        df = _make_ohlcv()
        result = engine.compute_all(df, indicator_names=[])
        assert "rsi_14" in result.columns

    def test_compute_all_no_close_column(self):
        """Line 147: DataFrame without close column → returns copy unchanged."""
        engine = IndicatorEngine()
        df = pd.DataFrame({"x": [1, 2, 3]})
        result = engine.compute_all(df, indicator_names=["rsi_14"])
        assert "rsi_14" not in result.columns
        assert list(result.columns) == ["x"]

    def test_sma_20_and_50(self):
        """Lines 156, 158: compute sma_20, sma_50."""
        engine = IndicatorEngine()
        df = _make_ohlcv(60)
        result = engine.compute_all(df, indicator_names=["sma_20", "sma_50"])
        assert "sma_20" in result.columns
        assert "sma_50" in result.columns

    def test_ema_12_and_26(self):
        """Lines 160, 162: compute ema_12, ema_26."""
        engine = IndicatorEngine()
        df = _make_ohlcv(60)
        result = engine.compute_all(df, indicator_names=["ema_12", "ema_26"])
        assert "ema_12" in result.columns
        assert "ema_26" in result.columns

    def test_macd_columns(self):
        """Lines 166-168: compute macd, macd_signal, macd_histogram."""
        engine = IndicatorEngine()
        df = _make_ohlcv(60)
        result = engine.compute_all(df, indicator_names=["macd", "macd_signal", "macd_histogram"])
        assert "macd" in result.columns
        assert "macd_signal" in result.columns
        assert "macd_histogram" in result.columns

    def test_rsi_14(self):
        """Line 173: compute rsi_14."""
        engine = IndicatorEngine()
        df = _make_ohlcv(60)
        result = engine.compute_all(df, indicator_names=["rsi_14"])
        assert "rsi_14" in result.columns

    def test_stochastic(self):
        """Lines 175-177: compute stoch_k, stoch_d."""
        engine = IndicatorEngine()
        df = _make_ohlcv(60)
        result = engine.compute_all(df, indicator_names=["stoch_k", "stoch_d"])
        assert "stoch_k" in result.columns
        assert "stoch_d" in result.columns

    def test_williams_r(self):
        """Line 180: compute williams_r_14."""
        engine = IndicatorEngine()
        df = _make_ohlcv(60)
        result = engine.compute_all(df, indicator_names=["williams_r_14"])
        assert "williams_r_14" in result.columns

    def test_atr_14(self):
        """Line 183: compute atr_14."""
        engine = IndicatorEngine()
        df = _make_ohlcv(60)
        result = engine.compute_all(df, indicator_names=["atr_14"])
        assert "atr_14" in result.columns

    def test_bollinger_bands(self):
        """Lines 186-188: compute bb_upper, bb_middle, bb_lower."""
        engine = IndicatorEngine()
        df = _make_ohlcv(60)
        result = engine.compute_all(df, indicator_names=["bb_upper", "bb_middle", "bb_lower"])
        assert "bb_upper" in result.columns
        assert "bb_middle" in result.columns
        assert "bb_lower" in result.columns

    def test_adx_14(self):
        """Line 191: compute adx_14."""
        engine = IndicatorEngine()
        df = _make_ohlcv(60)
        result = engine.compute_all(df, indicator_names=["adx_14"])
        assert "adx_14" in result.columns

    def test_obv(self):
        """Line 193: compute obv."""
        engine = IndicatorEngine()
        df = _make_ohlcv(60)
        result = engine.compute_all(df, indicator_names=["obv"])
        assert "obv" in result.columns

    def test_vwap(self):
        """Line 195: compute vwap."""
        engine = IndicatorEngine()
        df = _make_ohlcv(60)
        result = engine.compute_all(df, indicator_names=["vwap"])
        assert "vwap" in result.columns

    def test_mfi_14(self):
        """Line 197: compute mfi_14."""
        engine = IndicatorEngine()
        df = _make_ohlcv(60)
        result = engine.compute_all(df, indicator_names=["mfi_14"])
        assert "mfi_14" in result.columns

    def test_volume_sma_20(self):
        """Line 199: compute volume_sma_20."""
        engine = IndicatorEngine()
        df = _make_ohlcv(60)
        result = engine.compute_all(df, indicator_names=["volume_sma_20"])
        assert "volume_sma_20" in result.columns

    def test_volume_ratio(self):
        """Line 201: compute volume_ratio."""
        engine = IndicatorEngine()
        df = _make_ohlcv(60)
        result = engine.compute_all(df, indicator_names=["volume_ratio"])
        assert "volume_ratio" in result.columns

    def test_mixed_indicator_names(self):
        """Request a mix of indicators — all should appear."""
        engine = IndicatorEngine()
        df = _make_ohlcv(80)
        result = engine.compute_all(
            df,
            indicator_names=[
                "sma_20",
                "rsi_14",
                "macd",
                "bb_upper",
                "adx_14",
                "obv",
            ],
        )
        assert "sma_20" in result.columns
        assert "rsi_14" in result.columns
        assert "macd" in result.columns
        assert "bb_upper" in result.columns
        assert "adx_14" in result.columns
        assert "obv" in result.columns


class TestIndicatorEngineMisc:
    def test_list_available(self):
        """list_available returns a list of all factor names."""
        engine = IndicatorEngine()
        names = engine.list_available()
        assert isinstance(names, list)
        assert len(names) >= 14

    def test_calculate_alias(self):
        """calculate is an alias for batch_calculate."""
        engine = IndicatorEngine()
        df = _make_ohlcv()
        result = engine.calculate(df)
        assert "rsi_14" in result.columns
