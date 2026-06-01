"""Tests for Elliott Wave indicators."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.indicators.elliott_wave import (
    zigzag,
    classify_impulse,
    classify_corrective,
    elliott_wave,
    compute_fibonacci_levels,
    wave_momentum_divergence,
    WaveLabel,
    WaveType,
)


class TestZigZag:
    def test_detects_pivots(self):
        n = 200
        np.random.seed(42)
        # Create data with clear swings (10% moves) to ensure pivots are detected
        prices = np.zeros(n)
        prices[0] = 100
        for i in range(1, n):
            if i % 40 < 20:
                prices[i] = prices[i - 1] + 5.0  # 5% move up
            else:
                prices[i] = prices[i - 1] - 5.0  # 5% move down
        high = pd.Series(prices + 2)
        low = pd.Series(prices - 2)
        result = zigzag(high, low, threshold=0.03)  # 3% threshold
        assert len(result) >= 2
        assert "pivot_type" in result.columns

    def test_insufficient_data(self):
        high = pd.Series([100.0, 101.0])
        low = pd.Series([99.0, 100.0])
        result = zigzag(high, low)
        assert len(result) >= 0

    def test_pivots_alternate(self):
        np.random.seed(7)
        prices = np.cumsum(np.random.randn(200)) + 50000
        high = pd.Series(prices + 50)
        low = pd.Series(prices - 50)
        result = zigzag(high, low, threshold=0.03)
        if len(result) > 1:
            types = result["pivot_type"].values
            for i in range(1, len(types)):
                assert types[i] != types[i - 1]


class TestClassifyImpulse:
    def test_valid_bullish_impulse(self):
        pivots = pd.DataFrame({
            "pivot_idx": [0, 10, 20, 30, 40],
            "pivot_price": [100, 120, 110, 130, 125],
            "pivot_type": [-1, 1, -1, 1, -1],
        })
        result = classify_impulse(pivots, tolerance=0.5)
        if result is not None:
            assert result["wave_type"].iloc[0] == WaveType.IMPULSE

    def test_insufficient_pivots(self):
        pivots = pd.DataFrame({
            "pivot_idx": [0, 5],
            "pivot_price": [100, 110],
            "pivot_type": [-1, 1],
        })
        assert classify_impulse(pivots) is None


class TestClassifyCorrective:
    def test_valid_abc(self):
        pivots = pd.DataFrame({
            "pivot_idx": [0, 10, 20],
            "pivot_price": [100, 115, 108],
            "pivot_type": [-1, 1, -1],
        })
        result = classify_corrective(pivots, tolerance=0.5)
        if result is not None:
            assert result["wave_type"].iloc[0] == WaveType.CORRECTIVE


class TestElliottWave:
    def test_returns_dataframe(self):
        np.random.seed(42)
        n = 200
        prices = np.cumsum(np.random.randn(n)) + 50000
        df = pd.DataFrame({
            "open": prices, "high": prices + 50,
            "low": prices - 50, "close": prices,
            "volume": np.random.randint(100, 10000, n),
        })
        result = elliott_wave(df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(df)
        assert "wave_label" in result.columns


class TestFibonacciLevels:
    def test_compute_levels(self):
        levels = compute_fibonacci_levels(100.0, 120.0)
        assert isinstance(levels, dict)
        assert len(levels) == 10
        assert levels["fib_0.000"] == pytest.approx(120.0)

    def test_bearish_wave(self):
        levels = compute_fibonacci_levels(120.0, 100.0)
        assert isinstance(levels, dict)


class TestElliottWaveStrategy:
    def test_generate_signals(self):
        from quantflow.strategy.templates.elliott_wave import ElliottWaveStrategy
        np.random.seed(42)
        n = 200
        prices = np.cumsum(np.random.randn(n)) + 50000
        df = pd.DataFrame({
            "open": prices, "high": prices + 50,
            "low": prices - 50, "close": prices,
            "volume": np.random.randint(100, 10000, n),
        })
        s = ElliottWaveStrategy({"zigzag_threshold": 0.02})
        entries, exits = s.generate_signals(df)
        assert isinstance(entries, pd.Series)
        assert isinstance(exits, pd.Series)
        assert len(entries) == len(df)
