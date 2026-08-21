"""Tests for s5 risk-parity position sizing."""

from __future__ import annotations

from quantflow.common.models import Direction, Portfolio, Signal
from quantflow.signal.position_sizer import PositionSizer


def _signal(strength: float = 1.0, strategy: str = "trend") -> Signal:
    return Signal(
        symbol="BTC/USDT", direction=Direction.LONG, strength=strength, strategy_id=strategy
    )


def _portfolio() -> Portfolio:
    return Portfolio(cash=100000.0, positions={}, current_drawdown=0.0)


def _sizer() -> PositionSizer:
    return PositionSizer(
        method="risk_parity",
        max_position_pct=0.20,
        min_order_notional=10.0,
        fee_rate=0.001,
    )


class TestRiskParitySizing:
    def test_weight_one_full_strength(self) -> None:
        """Weight 1.0 + strength 1.0 → notional = total_value (capped by 20%)."""
        sizer = _sizer()
        size = sizer.size(_signal(), _portfolio(), allocation=1.0)
        # 100000 * 1.0 * 1.0 = 100000, capped to 20% = 20000, minus fees.
        assert size <= 20000.0
        assert size > 19000.0

    def test_weight_half_scales_notional(self) -> None:
        """Below the 20% cap, halving the weight halves the notional."""
        sizer = _sizer()
        # 0.10 × 100000 = 10000 and 0.05 × 100000 = 5000 — both under the
        # 20000 cap, so the ratio is clean.
        size_full = sizer.size(_signal(), _portfolio(), allocation=0.10)
        size_half = sizer.size(_signal(), _portfolio(), allocation=0.05)
        assert abs(size_half - size_full / 2) < 1.0

    def test_zero_weight_returns_zero(self) -> None:
        sizer = _sizer()
        assert sizer.size(_signal(), _portfolio(), allocation=0.0) == 0.0

    def test_strength_scales(self) -> None:
        sizer = _sizer()
        size_strong = sizer.size(_signal(strength=1.0), _portfolio(), allocation=0.5)
        size_weak = sizer.size(_signal(strength=0.25), _portfolio(), allocation=0.5)
        assert size_weak < size_strong

    def test_max_position_cap_enforced(self) -> None:
        """Even with weight 1.0 the 20% single-name cap must hold."""
        sizer = _sizer()
        size = sizer.size(_signal(), _portfolio(), allocation=1.0)
        assert size <= 20000.0

    def test_small_order_skipped(self) -> None:
        sizer = _sizer()
        size = sizer.size(_signal(strength=0.001), _portfolio(), allocation=0.001)
        assert size == 0.0

    def test_existing_position_deducted(self) -> None:
        sizer = _sizer()
        from quantflow.common.models import Position

        pos = Position(
            symbol="BTC/USDT",
            quantity=1.0,
            entry_price=5000.0,
            current_price=5000.0,
            unrealized_pnl=0.0,
            strategy_id="trend",
        )
        portfolio = Portfolio(cash=50000.0, positions={"BTC/USDT": pos}, current_drawdown=0.0)
        size = sizer.size(_signal(), portfolio, allocation=1.0)
        # 100000*1.0 = 100000 → cap 20% = 20000 → deduct existing 5000 → fees.
        assert size <= 15000.0
