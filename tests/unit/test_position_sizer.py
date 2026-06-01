"""Tests for quantflow.signal.position_sizer."""


from quantflow.common.models import Direction, Portfolio, Position, Signal
from quantflow.signal.position_sizer import PositionSizer


class TestPositionSizer:
    def test_basic_sizing(self):
        sizer = PositionSizer(kelly_fraction=0.5, max_position_pct=0.20)
        sig = Signal("BTC/USDT", Direction.LONG, 1.0, 50000)
        pf = Portfolio(cash=100000)
        size = sizer.size(sig, pf, win_rate=0.55, win_loss_ratio=2.0)
        assert size > 0

    def test_strength_scaling(self):
        sizer = PositionSizer(kelly_fraction=0.5, max_position_pct=0.20)
        pf = Portfolio(cash=100000)
        sig_strong = Signal("BTC/USDT", Direction.LONG, 1.0, 50000)
        sig_weak = Signal("BTC/USDT", Direction.LONG, 0.3, 50000)
        strong = sizer.size(sig_strong, pf, 0.55, 2.0)
        weak = sizer.size(sig_weak, pf, 0.55, 2.0)
        assert strong > weak

    def test_max_position_cap(self):
        sizer = PositionSizer(kelly_fraction=1.0, max_position_pct=0.10)
        sig = Signal("BTC/USDT", Direction.LONG, 1.0, 50000)
        pf = Portfolio(cash=100000)
        size = sizer.size(sig, pf, win_rate=0.99, win_loss_ratio=10.0)
        assert size <= 10000  # 10% of 100k

    def test_zero_equity(self):
        sizer = PositionSizer()
        sig = Signal("BTC/USDT", Direction.LONG, 1.0, 50000)
        pf = Portfolio(cash=0)
        assert sizer.size(sig, pf, 0.55, 2.0) == 0.0

    def test_negative_win_rate(self):
        sizer = PositionSizer(kelly_fraction=0.5)
        sig = Signal("BTC/USDT", Direction.LONG, 1.0, 50000)
        pf = Portfolio(cash=100000)
        assert sizer.size(sig, pf, win_rate=0.1, win_loss_ratio=0.5) == 0.0

    def test_fixed_method(self):
        sizer = PositionSizer(method="fixed", fixed_pct=0.05)
        sig = Signal("BTC/USDT", Direction.LONG, 1.0, 50000)
        pf = Portfolio(cash=100000)
        size = sizer.size(sig, pf)
        assert size > 0

    def test_existing_position_deduction(self):
        sizer = PositionSizer(kelly_fraction=0.5, max_position_pct=0.20)
        pos = Position("BTC/USDT", 0.5, 50000, 50000)
        pf = Portfolio(cash=50000, positions={"BTC/USDT": pos})
        sig = Signal("BTC/USDT", Direction.LONG, 0.5, 50000)
        size = sizer.size(sig, pf, 0.55, 2.0)
        assert size >= 0
