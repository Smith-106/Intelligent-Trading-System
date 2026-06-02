"""End-to-end test: indicators → strategies → signal generation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.indicators.engine import IndicatorEngine
from quantflow.strategy.templates.mean_reversion import MeanReversionStrategy
from quantflow.strategy.templates.trend_following import TrendFollowingStrategy


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing."""
    np.random.seed(42)
    n = 500
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    returns = np.random.normal(0.001, 0.03, n)
    trend = np.linspace(0, 0.3, n)
    close = 42000 * np.exp(np.cumsum(returns) + trend * 0.002)

    high = close * (1 + np.abs(np.random.normal(0, 0.01, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.01, n)))
    open_ = close * (1 + np.random.normal(0, 0.005, n))
    volume = np.random.uniform(500, 2000, n)

    df = pd.DataFrame(
        {
            "timestamp": (dates.astype(int) // 10**6),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )
    df.index.name = "datetime"
    return df


class TestIndicatorEngine:
    def test_batch_calculate(self, sample_ohlcv: pd.DataFrame) -> None:
        engine = IndicatorEngine()
        result = engine.batch_calculate(sample_ohlcv)
        assert "rsi_14" in result.columns
        assert "atr_14" in result.columns
        assert "macd" in result.columns

    def test_rsi_range(self, sample_ohlcv: pd.DataFrame) -> None:
        engine = IndicatorEngine()
        result = engine.batch_calculate(sample_ohlcv)
        rsi = result["rsi_14"].dropna()
        assert rsi.min() >= 0
        assert rsi.max() <= 100

    def test_atr_positive(self, sample_ohlcv: pd.DataFrame) -> None:
        engine = IndicatorEngine()
        result = engine.batch_calculate(sample_ohlcv)
        atr = result["atr_14"].dropna()
        assert (atr > 0).all()


class TestTrendFollowing:
    def test_generate_signals(self, sample_ohlcv: pd.DataFrame) -> None:
        strategy = TrendFollowingStrategy()
        entries, exits = strategy.generate_signals(sample_ohlcv)
        assert len(entries) == len(sample_ohlcv)
        assert len(exits) == len(sample_ohlcv)
        assert entries.dtype == bool
        assert exits.dtype == bool


class TestMeanReversion:
    def test_generate_signals(self, sample_ohlcv: pd.DataFrame) -> None:
        strategy = MeanReversionStrategy()
        entries, _exits = strategy.generate_signals(sample_ohlcv)
        assert len(entries) == len(sample_ohlcv)
        assert entries.dtype == bool
