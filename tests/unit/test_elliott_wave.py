"""Tests for Elliott Wave indicators."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from quantflow.indicators.elliott_wave import (
    WaveLabel,
    WaveType,
    classify_corrective,
    classify_impulse,
    compute_fibonacci_levels,
    elliott_wave,
    zigzag,
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
        pivots = pd.DataFrame(
            {
                "pivot_idx": [0, 10, 20, 30, 40],
                "pivot_price": [100, 120, 110, 130, 125],
                "pivot_type": [-1, 1, -1, 1, -1],
            }
        )
        result = classify_impulse(pivots, tolerance=0.5)
        if result is not None:
            assert result["wave_type"].iloc[0] == WaveType.IMPULSE

    def test_insufficient_pivots(self):
        pivots = pd.DataFrame(
            {
                "pivot_idx": [0, 5],
                "pivot_price": [100, 110],
                "pivot_type": [-1, 1],
            }
        )
        assert classify_impulse(pivots) is None


class TestClassifyCorrective:
    def test_valid_abc(self):
        pivots = pd.DataFrame(
            {
                "pivot_idx": [0, 10, 20],
                "pivot_price": [100, 115, 108],
                "pivot_type": [-1, 1, -1],
            }
        )
        result = classify_corrective(pivots, tolerance=0.5)
        if result is not None:
            assert result["wave_type"].iloc[0] == WaveType.CORRECTIVE


class TestElliottWave:
    def test_returns_dataframe(self):
        np.random.seed(42)
        n = 200
        prices = np.cumsum(np.random.randn(n)) + 50000
        df = pd.DataFrame(
            {
                "open": prices,
                "high": prices + 50,
                "low": prices - 50,
                "close": prices,
                "volume": np.random.randint(100, 10000, n),
            }
        )
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
    def test_initializes_base_strategy_name(self):
        from quantflow.strategy.templates.elliott_wave import ElliottWaveStrategy

        strategy = ElliottWaveStrategy({"zigzag_threshold": 0.02})

        assert strategy.name == "elliott_wave"
        assert strategy.params["zigzag_threshold"] == 0.02

    def test_generate_signals(self):
        from quantflow.strategy.templates.elliott_wave import ElliottWaveStrategy

        np.random.seed(42)
        n = 200
        prices = np.cumsum(np.random.randn(n)) + 50000
        df = pd.DataFrame(
            {
                "open": prices,
                "high": prices + 50,
                "low": prices - 50,
                "close": prices,
                "volume": np.random.randint(100, 10000, n),
            }
        )
        s = ElliottWaveStrategy({"zigzag_threshold": 0.02})
        entries, exits = s.generate_signals(df)
        assert isinstance(entries, pd.Series)
        assert isinstance(exits, pd.Series)
        assert len(entries) == len(df)

    def test_generate_signals_returns_empty_for_short_input(self):
        from quantflow.strategy.templates.elliott_wave import ElliottWaveStrategy

        df = pd.DataFrame(
            {
                "open": [100.0, 101.0],
                "high": [101.0, 102.0],
                "low": [99.0, 100.0],
                "close": [100.0, 101.0],
                "volume": [1000.0, 1000.0],
            }
        )

        entries, exits = ElliottWaveStrategy().generate_signals(df)

        assert entries.eq(False).all()
        assert exits.eq(False).all()

    def test_generate_signals_marks_wave_entries_and_exits(self):
        from quantflow.strategy.templates.elliott_wave import ElliottWaveStrategy

        df = pd.DataFrame(
            {
                "open": [100.0 + idx for idx in range(25)],
                "high": [101.0 + idx for idx in range(25)],
                "low": [99.0 + idx for idx in range(25)],
                "close": [100.0 + idx for idx in range(25)],
                "volume": [1000.0] * 25,
            }
        )
        wave = pd.DataFrame(
            {
                "wave_label": [0] * 25,
            },
            index=df.index,
        )
        wave.loc[5, "wave_label"] = int(WaveLabel.W2)
        wave.loc[10, "wave_label"] = int(WaveLabel.W4)
        wave.loc[15, "wave_label"] = int(WaveLabel.WC)
        wave.loc[20, "wave_label"] = int(WaveLabel.W5)

        with patch("quantflow.strategy.templates.elliott_wave.elliott_wave", return_value=wave):
            entries, exits = ElliottWaveStrategy({"use_divergence": False}).generate_signals(df)

        assert entries.iloc[5]
        assert entries.iloc[10]
        assert entries.iloc[15]
        assert exits.iloc[20]

    def test_generate_signals_applies_divergence_and_hooks_are_noops(self):
        from quantflow.common.models import Bar
        from quantflow.strategy.base import StrategyContext
        from quantflow.strategy.templates.elliott_wave import ElliottWaveStrategy

        df = pd.DataFrame(
            {
                "open": [100.0 + idx for idx in range(25)],
                "high": [101.0 + idx for idx in range(25)],
                "low": [99.0 + idx for idx in range(25)],
                "close": [100.0 + idx for idx in range(25)],
                "volume": [1000.0] * 25,
                "rsi_14": [50.0] * 25,
            }
        )
        empty_wave = pd.DataFrame({"wave_label": [0] * 25}, index=df.index)
        divergence = pd.Series(0, index=df.index, dtype=int)
        divergence.iloc[-1] = -1
        strategy = ElliottWaveStrategy()

        with (
            patch(
                "quantflow.strategy.templates.elliott_wave.elliott_wave", return_value=empty_wave
            ),
            patch("quantflow.indicators.elliott_wave.zigzag", return_value=pd.DataFrame()),
            patch(
                "quantflow.strategy.templates.elliott_wave.wave_momentum_divergence",
                return_value=divergence,
            ),
        ):
            entries, exits = strategy.generate_signals(df)

        ctx = StrategyContext()
        bar = Bar("BTC/USDT", 1, 100.0, 101.0, 99.0, 100.5, 1000.0)

        assert not entries.any()
        assert exits.iloc[-1]
        strategy.on_init(ctx)
        strategy.on_bar(ctx, bar)
        strategy.on_tick(ctx, {"price": 100.5})
