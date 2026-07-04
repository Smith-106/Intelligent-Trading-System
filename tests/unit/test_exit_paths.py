"""Systematic _check_position_exits tests for all strategy templates — P1-2."""

from __future__ import annotations

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyContext
from quantflow.strategy.templates.trend_following import TrendFollowingStrategy
from quantflow.strategy.templates.volatility_breakout import VolatilityBreakoutStrategy
from quantflow.strategy.templates.mean_reversion import MeanReversionStrategy
from quantflow.strategy.templates.funding_rate import FundingRateStrategy
from quantflow.strategy.templates.momentum_rotation import MomentumRotationStrategy


def _make_bar(price: float = 100.0, high: float = 101.0, low: float = 99.0, idx: int = 0) -> Bar:
    return Bar("BTC/USDT", 1700000000 + idx * 60000, price - 0.5, high, low, price, 1000.0)


class _FakeContext(StrategyContext):
    def __init__(self):
        self.signals: list[tuple] = []

    def emit_signal(self, symbol, direction, strength=1.0, price=0.0, strategy_id=""):
        self.signals.append((symbol, direction, strength, price, strategy_id))


# ---------------------------------------------------------------------------
# TrendFollowing — profit target + trailing stop + max holding
# ---------------------------------------------------------------------------

class TestTrendFollowingExits:
    def test_profit_target_exit(self):
        s = TrendFollowingStrategy(params={"profit_take_pct": 0.05})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 0
        s._highest_since_entry = 106.0

        bar = _make_bar(106.0)  # target = 105
        s._check_position_exits(ctx, bar)
        assert len(ctx.signals) == 1
        assert ctx.signals[0][1] == Direction.FLAT
        assert s._in_position is False

    def test_trailing_stop_exit(self):
        s = TrendFollowingStrategy(params={"trailing_stop_atr_mult": 2.0, "profit_take_pct": 1.0})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 0
        s._highest_since_entry = 110.0
        s._atr_values = [2.0]

        # trailing level = 110 - 2.0*2.0 = 106, close = 105 → triggers
        bar = _make_bar(105.0)
        s._check_position_exits(ctx, bar)
        assert len(ctx.signals) == 1
        assert ctx.signals[0][1] == Direction.FLAT

    def test_max_holding_exit(self):
        s = TrendFollowingStrategy(params={"max_holding_bars": 5, "profit_take_pct": 1.0})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 4  # incremented to 5
        s._highest_since_entry = 101.0
        s._atr_values = [1.0]

        bar = _make_bar(101.0)
        s._check_position_exits(ctx, bar)
        assert len(ctx.signals) == 1
        assert ctx.signals[0][1] == Direction.FLAT

    def test_no_exit_when_not_in_position(self):
        s = TrendFollowingStrategy()
        ctx = _FakeContext()
        s._in_position = False
        s._check_position_exits(ctx, _make_bar(200.0))
        assert len(ctx.signals) == 0

    def test_highest_since_entry_updates(self):
        s = TrendFollowingStrategy(params={"profit_take_pct": 1.0, "max_holding_bars": 100})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 0
        s._highest_since_entry = 100.0
        s._atr_values = [1.0]

        bar = _make_bar(102.0, high=105.0)
        s._check_position_exits(ctx, bar)
        assert s._highest_since_entry == 105.0


# ---------------------------------------------------------------------------
# VolatilityBreakout — direction-aware profit + trailing + max holding
# ---------------------------------------------------------------------------

class TestVolatilityBreakoutExits:
    def test_long_profit_target_exit(self):
        s = VolatilityBreakoutStrategy(params={"profit_take_pct": 0.05})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_direction = Direction.LONG
        s._entry_price = 100.0
        s._bars_since_entry = 0
        s._highest_since_entry = 106.0
        s._lowest_since_entry = 99.0

        bar = _make_bar(106.0)  # target = 105
        s._check_position_exits(ctx, bar)
        assert len(ctx.signals) == 1
        assert ctx.signals[0][1] == Direction.FLAT

    def test_short_profit_target_exit(self):
        s = VolatilityBreakoutStrategy(params={"profit_take_pct": 0.05})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_direction = Direction.SHORT
        s._entry_price = 100.0
        s._bars_since_entry = 0
        s._highest_since_entry = 101.0
        s._lowest_since_entry = 95.0

        bar = _make_bar(94.0)  # target = 95 → close <= 95 triggers
        s._check_position_exits(ctx, bar)
        assert len(ctx.signals) == 1
        assert ctx.signals[0][1] == Direction.FLAT

    def test_short_trailing_stop_exit(self):
        s = VolatilityBreakoutStrategy(params={"trailing_stop_atr_mult": 2.0, "profit_take_pct": 1.0})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_direction = Direction.SHORT
        s._entry_price = 100.0
        s._bars_since_entry = 0
        s._lowest_since_entry = 90.0
        s._highest_since_entry = 101.0
        s._atr_values = [2.0]

        # trailing = 90 + 2.0*2.0 = 94, close = 95 > 94 → triggers
        bar = _make_bar(95.0)
        s._check_position_exits(ctx, bar)
        assert len(ctx.signals) == 1
        assert ctx.signals[0][1] == Direction.FLAT

    def test_max_holding_exit(self):
        s = VolatilityBreakoutStrategy(params={"max_holding_bars": 3, "profit_take_pct": 1.0})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_direction = Direction.LONG
        s._entry_price = 100.0
        s._bars_since_entry = 2  # incremented to 3
        s._highest_since_entry = 101.0
        s._lowest_since_entry = 99.0

        bar = _make_bar(101.0)
        s._check_position_exits(ctx, bar)
        assert len(ctx.signals) == 1

    def test_no_exit_when_not_in_position(self):
        s = VolatilityBreakoutStrategy()
        ctx = _FakeContext()
        s._in_position = False
        s._check_position_exits(ctx, _make_bar(200.0))
        assert len(ctx.signals) == 0


# ---------------------------------------------------------------------------
# MeanReversion — direction-aware profit target + max holding
# ---------------------------------------------------------------------------

class TestMeanReversionExits:
    def test_long_profit_target_exit(self):
        s = MeanReversionStrategy(params={"profit_take_pct": 0.03})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_direction = Direction.LONG
        s._entry_price = 100.0
        s._bars_since_entry = 0

        bar = _make_bar(104.0)  # target = 103
        s._check_position_exits(ctx, bar)
        assert len(ctx.signals) == 1
        assert ctx.signals[0][1] == Direction.FLAT

    def test_short_profit_target_exit(self):
        s = MeanReversionStrategy(params={"profit_take_pct": 0.03})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_direction = Direction.SHORT
        s._entry_price = 100.0
        s._bars_since_entry = 0

        bar = _make_bar(96.0)  # target = 97
        s._check_position_exits(ctx, bar)
        assert len(ctx.signals) == 1
        assert ctx.signals[0][1] == Direction.FLAT

    def test_max_holding_exit(self):
        s = MeanReversionStrategy(params={"max_holding_bars": 5, "profit_take_pct": 1.0})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_direction = Direction.LONG
        s._entry_price = 100.0
        s._bars_since_entry = 4  # incremented to 5

        bar = _make_bar(101.0)
        s._check_position_exits(ctx, bar)
        assert len(ctx.signals) == 1
        assert ctx.signals[0][1] == Direction.FLAT

    def test_no_exit_when_not_in_position(self):
        s = MeanReversionStrategy()
        ctx = _FakeContext()
        s._in_position = False
        s._check_position_exits(ctx, _make_bar(200.0))
        assert len(ctx.signals) == 0


# ---------------------------------------------------------------------------
# FundingRate — direction-aware profit target + max holding
# ---------------------------------------------------------------------------

class TestFundingRateExits:
    def test_long_profit_target_exit(self):
        s = FundingRateStrategy(params={"profit_take_pct": 0.02})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_direction = Direction.LONG
        s._entry_price = 100.0
        s._bars_since_entry = 0

        bar = _make_bar(103.0)  # target = 102
        s._check_position_exits(ctx, bar)
        assert len(ctx.signals) == 1
        assert ctx.signals[0][1] == Direction.FLAT

    def test_short_profit_target_exit(self):
        s = FundingRateStrategy(params={"profit_take_pct": 0.02})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_direction = Direction.SHORT
        s._entry_price = 100.0
        s._bars_since_entry = 0

        bar = _make_bar(97.0)  # target = 98
        s._check_position_exits(ctx, bar)
        assert len(ctx.signals) == 1
        assert ctx.signals[0][1] == Direction.FLAT

    def test_max_holding_exit(self):
        s = FundingRateStrategy(params={"max_holding_bars": 4, "profit_take_pct": 1.0})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_direction = Direction.LONG
        s._entry_price = 100.0
        s._bars_since_entry = 3  # incremented to 4

        bar = _make_bar(101.0)
        s._check_position_exits(ctx, bar)
        assert len(ctx.signals) == 1
        assert ctx.signals[0][1] == Direction.FLAT

    def test_no_exit_when_not_in_position(self):
        s = FundingRateStrategy()
        ctx = _FakeContext()
        s._in_position = False
        s._check_position_exits(ctx, _make_bar(200.0))
        assert len(ctx.signals) == 0


# ---------------------------------------------------------------------------
# MomentumRotation — stop-loss + profit target + max holding
# ---------------------------------------------------------------------------

class TestMomentumRotationExits:
    def test_stop_loss_exit(self):
        s = MomentumRotationStrategy(params={"stop_loss_pct": 0.05, "profit_take_pct": 1.0})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 0

        # 5% drop: close = 94, drawdown = -6% < -5%
        bar = _make_bar(94.0)
        s._check_position_exits(ctx, bar)
        assert len(ctx.signals) == 1
        assert ctx.signals[0][1] == Direction.FLAT
        assert s._in_position is False

    def test_profit_target_exit(self):
        s = MomentumRotationStrategy(params={"profit_take_pct": 0.08, "stop_loss_pct": 0.0})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 0

        bar = _make_bar(109.0)  # target = 108
        s._check_position_exits(ctx, bar)
        assert len(ctx.signals) == 1
        assert ctx.signals[0][1] == Direction.FLAT

    def test_max_holding_exit(self):
        s = MomentumRotationStrategy(params={"max_holding_bars": 5, "profit_take_pct": 1.0, "stop_loss_pct": 0.0})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 4  # incremented to 5

        bar = _make_bar(101.0)
        s._check_position_exits(ctx, bar)
        assert len(ctx.signals) == 1
        assert ctx.signals[0][1] == Direction.FLAT

    def test_no_exit_when_not_in_position(self):
        s = MomentumRotationStrategy()
        ctx = _FakeContext()
        s._in_position = False
        s._check_position_exits(ctx, _make_bar(200.0))
        assert len(ctx.signals) == 0

    def test_no_stop_loss_when_pct_zero(self):
        s = MomentumRotationStrategy(params={"stop_loss_pct": 0.0, "profit_take_pct": 1.0, "max_holding_bars": 100})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 0

        # Even with 50% drop, stop loss won't fire when pct=0
        bar = _make_bar(50.0)
        s._check_position_exits(ctx, bar)
        assert len(ctx.signals) == 0  # no exit triggered
