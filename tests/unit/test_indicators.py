"""Unit tests for indicator engine and factor registry."""

import numpy as np
import pandas as pd
import pytest

from quantflow.indicators.base import FactorBase, FactorRegistry
from quantflow.indicators.engine import FACTOR_NAMES, IndicatorEngine


@pytest.fixture
def ohlcv_df():
    np.random.seed(42)
    n = 200
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    close = 42000 * np.exp(np.cumsum(np.random.normal(0.001, 0.02, n)))
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.random.uniform(500, 2000, n),
        },
        index=dates,
    )


class TestFactorRegistry:
    def test_register_and_get(self):
        registry = FactorRegistry()

        class TestFactor(FactorBase):
            name = "test_factor"

            def compute(self, df, **params):
                return df["close"] * 2

        registry.register(TestFactor)
        assert "test_factor" in registry.list_factors()
        assert registry.get("test_factor") == TestFactor

    def test_missing_factor(self):
        registry = FactorRegistry()
        result = registry.get("nonexistent")
        assert result is None

    def test_compute(self, ohlcv_df):
        registry = FactorRegistry()

        class DoubleClose(FactorBase):
            name = "double_close"

            def compute(self, df, **params):
                return df["close"] * 2

        registry.register(DoubleClose)
        result = registry.compute("double_close", ohlcv_df)
        assert len(result) == len(ohlcv_df)
        assert result.iloc[-1] == ohlcv_df["close"].iloc[-1] * 2


class TestIndicatorEngine:
    def test_batch_calculate(self, ohlcv_df):
        engine = IndicatorEngine()
        result = engine.batch_calculate(ohlcv_df)
        assert "rsi_14" in result.columns
        assert "atr_14" in result.columns
        assert "sma_20" in result.columns
        assert "adx_14" in result.columns
        assert "vwap" in result.columns
        assert len(result) == len(ohlcv_df)

    def test_calculate_alias(self, ohlcv_df):
        engine = IndicatorEngine()
        result = engine.calculate(ohlcv_df)
        assert "rsi_14" in result.columns

    def test_21_core_factors(self, ohlcv_df):
        engine = IndicatorEngine()
        result = engine.batch_calculate(ohlcv_df)
        available = engine.list_available()
        # 21 core factors always computed by batch_calculate
        # 6 additional Elliott Wave factors registered but require explicit params
        core_factor_names = [
            f
            for f in FACTOR_NAMES
            if f
            not in {
                "zigzag_pivots",
                "wave_count",
                "fibonacci_levels",
                "critical_levels",
                "wave_channel",
                "divergence",
            }
        ]
        core_factors = [f for f in available if f in core_factor_names]
        assert len(core_factors) == 21
        for name in core_factors:
            assert name in result.columns, f"Factor {name} not in result"

    def test_rsi_range(self, ohlcv_df):
        engine = IndicatorEngine()
        result = engine.batch_calculate(ohlcv_df)
        rsi = result["rsi_14"].dropna()
        assert rsi.min() >= 0
        assert rsi.max() <= 100

    def test_atr_positive(self, ohlcv_df):
        engine = IndicatorEngine()
        result = engine.batch_calculate(ohlcv_df)
        atr = result["atr_14"].dropna()
        assert (atr > 0).all()
