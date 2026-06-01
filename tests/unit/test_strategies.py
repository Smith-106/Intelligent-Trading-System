"""Tests for quantflow.strategy.templates."""

import numpy as np
import pandas as pd

from quantflow.common.models import Bar
from quantflow.strategy.base import StrategyContext
from quantflow.strategy.templates.mean_reversion import MeanReversionStrategy
from quantflow.strategy.templates.trend_following import TrendFollowingStrategy


def _make_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
    np.random.seed(seed)
    close = 100 + np.random.randn(n).cumsum()
    return pd.DataFrame({
        "close": close,
        "high": close + np.abs(np.random.randn(n)),
        "low": close - np.abs(np.random.randn(n)),
        "volume": 1000 + np.abs(np.random.randn(n) * 100),
    })


class TestTrendFollowingStrategy:
    def test_generate_signals(self):
        strategy = TrendFollowingStrategy()
        df = _make_ohlcv(200)
        entries, exits = strategy.generate_signals(df)
        assert len(entries) == len(df)
        assert len(exits) == len(df)
        assert entries.dtype == bool
        assert exits.dtype == bool

    def test_short_data(self):
        strategy = TrendFollowingStrategy()
        df = _make_ohlcv(10)
        entries, _exits = strategy.generate_signals(df)
        assert len(entries) == 10

    def test_on_bar(self):
        strategy = TrendFollowingStrategy()
        ctx = StrategyContext()
        strategy.on_init(ctx)
        # Feed enough bars to trigger signal generation
        for i in range(60):
            bar = Bar("BTC/USDT", 1000 + i * 60000, 100 + i * 0.5, 101 + i * 0.5, 99 + i * 0.5, 100.5 + i * 0.5, 1000)
            strategy.on_bar(ctx, bar)
        # Should have accumulated bars without error

    def test_required_indicators(self):
        strategy = TrendFollowingStrategy()
        indicators = strategy.get_required_indicators()
        assert len(indicators) > 0


class TestMeanReversionStrategy:
    def test_generate_signals(self):
        strategy = MeanReversionStrategy()
        df = _make_ohlcv(200)
        entries, exits = strategy.generate_signals(df)
        assert len(entries) == len(df)
        assert len(exits) == len(df)

    def test_short_data(self):
        strategy = MeanReversionStrategy()
        df = _make_ohlcv(5)
        entries, _exits = strategy.generate_signals(df)
        assert len(entries) == 5

    def test_required_indicators(self):
        strategy = MeanReversionStrategy()
        indicators = strategy.get_required_indicators()
        assert len(indicators) > 0
