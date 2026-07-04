"""Tests for quantflow.signal.generator."""

import pytest

from quantflow.common.models import Direction, Signal
from quantflow.signal.generator import SignalGenerator


class TestSignalGenerator:
    def test_generate_long(self):
        gen = SignalGenerator()
        sig = gen.generate_signal(Direction.LONG, 0.8, "BTC/USDT", 50000, "trend")
        assert sig is not None
        assert sig.direction == Direction.LONG
        assert sig.strength == 0.8

    def test_generate_short(self):
        gen = SignalGenerator()
        sig = gen.generate_signal(Direction.SHORT, 0.6, "BTC/USDT", 50000, "trend")
        assert sig is not None
        assert sig.direction == Direction.SHORT

    def test_flat_returns_none(self):
        gen = SignalGenerator()
        sig = gen.generate_signal(Direction.FLAT, 0.5, "BTC/USDT", 50000)
        assert sig is None

    def test_strength_clamped(self):
        gen = SignalGenerator()
        sig = gen.generate_signal(Direction.LONG, 1.5, "BTC/USDT", 50000)
        assert sig.strength == 1.0

    def test_consolidate_same_direction(self):
        gen = SignalGenerator()
        sigs = [
            Signal("BTC/USDT", Direction.LONG, 0.6, 50000, "s1"),
            Signal("BTC/USDT", Direction.LONG, 0.8, 50000, "s2"),
        ]
        # With hit_rates=1.0, strength = weighted avg = (0.6+0.8)/2 = 0.7
        result = gen.consolidate_signals(sigs, strategy_hit_rates={"s1": 1.0, "s2": 1.0})
        assert result is not None
        assert result.direction == Direction.LONG
        assert result.strength == pytest.approx(0.7)

        # Without hit_rates, default 0.5 scaling: (0.6*0.5 + 0.8*0.5) / 2 = 0.35
        result_default = gen.consolidate_signals(sigs)
        assert result_default.strength == pytest.approx(0.35)

    def test_consolidate_conflicting(self):
        gen = SignalGenerator()
        sigs = [
            Signal("BTC/USDT", Direction.LONG, 0.8, 50000, "s1"),
            Signal("BTC/USDT", Direction.SHORT, 0.8, 50000, "s2"),
        ]
        result = gen.consolidate_signals(sigs)
        assert result is None  # conflicting signals cancel

    def test_consolidate_empty(self):
        gen = SignalGenerator()
        assert gen.consolidate_signals([]) is None

    def test_consolidate_short_bias(self):
        gen = SignalGenerator()
        sigs = [
            Signal("BTC/USDT", Direction.SHORT, 0.4, 49000, "s1"),
            Signal("BTC/USDT", Direction.SHORT, 0.8, 49000, "s2"),
        ]

        # With hit_rates=1.0: strength = (0.4+0.8)/2 = 0.6
        result = gen.consolidate_signals(sigs, strategy_hit_rates={"s1": 1.0, "s2": 1.0})

        assert result is not None
        assert result.direction == Direction.SHORT
        assert result.price == 49000
        assert result.strength == pytest.approx(0.6)
        assert set(result.strategy_id.split(",")) == {"s1", "s2"}
