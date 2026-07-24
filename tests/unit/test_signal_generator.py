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
        # ISS-022: strength-weighted mean Σ(strength_i·w_i)/Σ(w_i), w_i=strength·hit.
        # hit_rate=1.0 → w=strength → Σ(strength²)/Σ(strength) = (0.36+0.64)/1.4 = 0.7143
        result = gen.consolidate_signals(sigs, strategy_hit_rates={"s1": 1.0, "s2": 1.0})
        assert result is not None
        assert result.direction == Direction.LONG
        assert result.strength == pytest.approx(0.7143, abs=1e-3)

        # Constant hit_rate scaling cancels in the ratio (numerator & denominator
        # both scale by hit_rate), so default 0.5 == hit_rate=1.0 here.
        result_default = gen.consolidate_signals(sigs)
        assert result_default.strength == pytest.approx(0.7143, abs=1e-3)

    def test_consolidate_unanimous_strength_one(self):
        """ISS-022 regression: two unanimous strength=1.0 signals must NOT be
        halved to 0.5 (the old total_weight/n formula did). Weighted mean → 1.0."""
        gen = SignalGenerator()
        sigs = [
            Signal("BTC/USDT", Direction.LONG, 1.0, 50000, "s1"),
            Signal("BTC/USDT", Direction.LONG, 1.0, 50000, "s2"),
        ]
        result = gen.consolidate_signals(sigs, strategy_hit_rates={"s1": 0.5, "s2": 0.5})
        assert result is not None
        assert result.strength == pytest.approx(1.0)

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

        # ISS-022 weighted mean: Σ(strength²)/Σ(strength) = (0.16+0.64)/1.2 = 0.6667
        result = gen.consolidate_signals(sigs, strategy_hit_rates={"s1": 1.0, "s2": 1.0})

        assert result is not None
        assert result.direction == Direction.SHORT
        assert result.price == 49000
        assert result.strength == pytest.approx(0.6667, abs=1e-3)
        assert set(result.strategy_id.split(",")) == {"s1", "s2"}

    def test_consolidate_strategy_id_is_deterministic_sorted(self):
        """Consolidated strategy_id must be sorted so the same inputs always
        produce the same compound key (a plain set() join was non-deterministic
        and broke downstream budget/win-rate lookups across bars)."""
        gen = SignalGenerator()
        sigs_a = [
            Signal("BTC/USDT", Direction.LONG, 0.6, 50000, "zeta"),
            Signal("BTC/USDT", Direction.LONG, 0.8, 50000, "alpha"),
            Signal("BTC/USDT", Direction.LONG, 0.7, 50000, "mid"),
        ]
        sigs_b = list(reversed(sigs_a))
        a = gen.consolidate_signals(
            sigs_a, strategy_hit_rates={"zeta": 1.0, "alpha": 1.0, "mid": 1.0}
        )
        b = gen.consolidate_signals(
            sigs_b, strategy_hit_rates={"zeta": 1.0, "alpha": 1.0, "mid": 1.0}
        )
        assert a is not None and b is not None
        assert a.strategy_id == "alpha,mid,zeta"
        assert a.strategy_id == b.strategy_id  # input order independent
