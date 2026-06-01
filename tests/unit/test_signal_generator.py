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
        result = gen.consolidate_signals(sigs)
        assert result is not None
        assert result.direction == Direction.LONG
        assert result.strength == pytest.approx(0.7)

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
