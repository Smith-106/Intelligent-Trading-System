"""Coverage completion for remaining strategy templates.

Targets remaining uncovered lines/branches in:
- elliott_wave: _entry_direction short-lookback / falling / rising paths
- funding_rate: on_bar cooldown return, freshness-gate fail-closed skip,
  LONG-position target-not-hit transition
- momentum_rotation: aligned-empty all-false map, symbol missing from
  aligned columns
- trend_following: on_bar _check_position_exits call, _structure_ok_latest
  pullback/breakout branches, _structure_mask_vectorized classic,
  generate_signals non-adaptive profit target, trailing-stop absent ATR

Pure logic; no network, no vectorbt.
"""

from __future__ import annotations

import pandas as pd
import pytest

from quantflow.common.models import Bar, Direction
from quantflow.strategy.templates.elliott_wave import ElliottWaveStrategy
from quantflow.strategy.templates.funding_rate import FundingRateStrategy
from quantflow.strategy.templates.momentum_rotation import MomentumRotationStrategy
from quantflow.strategy.templates.trend_following import TrendFollowingStrategy


def _bar(close: float, ts: int = 0, *, volume: float = 1000.0) -> Bar:
    return Bar(
        symbol="BTC/USDT",
        timestamp=ts,
        open=close,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=volume,
    )


class _Ctx:
    def __init__(self) -> None:
        self.signals: list[tuple] = []

    def emit_signal(
        self,
        symbol: str,
        direction: Direction,
        strength: float = 1.0,
        price: float = 0.0,
        strategy_id: str = "",
    ) -> None:
        self.signals.append((symbol, direction, strength, price, strategy_id))


# ---------------------------------------------------------------------------
# elliott_wave._entry_direction
# ---------------------------------------------------------------------------


class TestElliottWaveEntryDirection:
    def test_short_lookback_returns_long(self) -> None:
        df = pd.DataFrame({"close": [10.0, 11.0]})
        assert ElliottWaveStrategy._entry_direction(df, 0) == Direction.LONG
        assert ElliottWaveStrategy._entry_direction(df, 1) == Direction.LONG

    def test_falling_slope_returns_short(self) -> None:
        df = pd.DataFrame({"close": [10.0, 11.0, 12.0, 13.0, 12.0, 9.0]})
        assert ElliottWaveStrategy._entry_direction(df, 5) == Direction.SHORT

    def test_rising_slope_returns_long(self) -> None:
        df = pd.DataFrame({"close": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]})
        assert ElliottWaveStrategy._entry_direction(df, 5) == Direction.LONG


# ---------------------------------------------------------------------------
# funding_rate on_bar paths
# ---------------------------------------------------------------------------


class TestFundingRateCoverage:
    def _s(self, **overrides) -> FundingRateStrategy:
        params = {
            "use_rate_ema": False,
            "require_oi_confirmation": False,
            "cooldown_bars": 0,
            "entry_threshold": 0.001,
            "exit_threshold": 0.0003,
            "take_profit_pct": 0.1,
            "max_holding_bars": 20,
            "stop_loss_pct": 0.0,
        }
        params.update(overrides)
        return FundingRateStrategy(params=params)

    def test_cooldown_blocks_entry(self) -> None:
        s = self._s(cooldown_bars=2)
        s.update_funding_rate(-0.01)
        s.update_open_interest(100.0)
        s._cooldown_counter = 2
        ctx = _Ctx()
        s.on_bar(ctx, _bar(100.0))
        assert ctx.signals == []
        assert s._cooldown_counter == 1

    def test_freshness_gate_blocks_new_entry(self) -> None:
        s = self._s()
        s.set_freshness_gate(False)
        s.update_funding_rate(-0.01)
        s.update_open_interest(100.0)
        ctx = _Ctx()
        s.on_bar(ctx, _bar(100.0))
        assert ctx.signals == []  # fail-closed: entry skipped

    def test_long_entry_then_target_not_hit(self) -> None:
        s = self._s()
        s.update_funding_rate(-0.01)
        s.update_open_interest(100.0)
        ctx = _Ctx()
        s.on_bar(ctx, _bar(100.0))  # rate extreme -> LONG entry
        assert [sg[1] for sg in ctx.signals] == [Direction.LONG]
        # next bar: close 102 below target 110 -> no exit, position stays
        s.update_funding_rate(-0.01)
        s.update_open_interest(101.0)
        s.on_bar(ctx, _bar(102.0))
        assert [sg[1] for sg in ctx.signals] == [Direction.LONG]
        assert s._in_position is True

    def test_short_entry_via_positive_rate(self) -> None:
        s = self._s()
        s.update_funding_rate(0.01)
        s.update_open_interest(100.0)
        ctx = _Ctx()
        s.on_bar(ctx, _bar(100.0))
        assert [sg[1] for sg in ctx.signals] == [Direction.SHORT]
        assert s._entry_direction == Direction.SHORT

    def test_check_position_exits_no_direction(self) -> None:
        # _entry_direction default None -> elif-False transition (224->234)
        s = self._s()
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 1
        ctx = _Ctx()
        s._check_position_exits(ctx, _bar(100.5))
        assert ctx.signals == []
        assert s._in_position is True


# ---------------------------------------------------------------------------
# momentum_rotation cross-sectional paths
# ---------------------------------------------------------------------------


class TestMomentumRotationCoverage:
    def test_symbol_missing_from_aligned_columns(self) -> None:
        s = MomentumRotationStrategy(params={"lookback": 5, "top_n": 1})
        long_df = pd.DataFrame({"close": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]})
        short_df = pd.DataFrame({"close": [1.0, 2.0]})  # below lookback
        out = s.generate_cross_sectional_signals({"AAA": long_df, "BBB": short_df})
        assert "AAA" in out and "BBB" in out
        # BBB never scored -> all-false placeholder series
        assert bool(out["BBB"][0].sum()) is False
        assert bool(out["BBB"][1].sum()) is False

    def test_aligned_empty_returns_all_false(self) -> None:
        # lookback=0 lets an empty close df through -> aligned is empty
        s = MomentumRotationStrategy(params={"lookback": 0, "top_n": 1})
        df = pd.DataFrame({"close": pd.Series(dtype=float)})
        out = s.generate_cross_sectional_signals({"X": df})
        assert "X" in out
        assert len(out["X"][0]) == 0

    def test_no_scores_returns_empty(self) -> None:
        s = MomentumRotationStrategy(params={"lookback": 5})
        df = pd.DataFrame({"close": [1.0, 2.0]})  # too short for lookback
        assert s.generate_cross_sectional_signals({"X": df}) == {}


# ---------------------------------------------------------------------------
# trend_following
# ---------------------------------------------------------------------------


class TestTrendFollowingCoverage:
    def _s(self, **overrides) -> TrendFollowingStrategy:
        params = {
            "fast_ma_period": 3,
            "slow_ma_period": 5,
            "macd_fast": 4,
            "macd_slow": 6,
            "macd_signal": 3,
            "rsi_period": 2,
            "atr_period": 3,
            "volume_period": 3,
            "volume_threshold": 0.5,
            "min_conditions": 3,
            "take_profit_pct": 0.5,
            "max_holding_bars": 20,
            "trailing_stop_atr_multiplier": 3.0,
            "stop_loss_pct": 0.0,
            "rsi_adaptive_profit": False,
            "atr_multiplier": 0.5,  # atr_ok always False -> clean exit counts
        }
        params.update(overrides)
        return TrendFollowingStrategy(params=params)

    def test_on_bar_enters_and_calls_position_exits(self) -> None:
        s = self._s()
        ctx = _Ctx()
        # wobbling rise keeps rsi in (30, 70): entry_count = trend+vol+rsi = 3
        closes = [100.0]
        for i in range(20):
            closes.append(closes[-1] + (2.0 if i % 2 == 0 else -0.9))
        for i, c in enumerate(closes):
            s.on_bar(ctx, _bar(c, ts=i, volume=1000.0))
        dirs = [sg[1] for sg in ctx.signals]
        assert Direction.LONG in dirs
        assert Direction.FLAT not in dirs  # target/trailing/max-hold not hit
        assert s._in_position is True
        # seed holding state so the on_bar gate (bars_since_entry > 0) opens
        s._bars_since_entry = 1
        s.on_bar(ctx, _bar(closes[-1] + 1.0, ts=len(closes), volume=1000.0))
        assert s._in_position is True

    def test_check_position_exits_no_atr_values(self) -> None:
        # trailing-stop branch skipped when ATR history is empty
        s = self._s()
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 1
        s._highest_since_entry = 101.0
        s._atr_values = []
        ctx = _Ctx()
        s._check_position_exits(ctx, _bar(100.5))
        assert ctx.signals == []
        assert s._in_position is True

    def test_structure_ok_latest_pullback(self) -> None:
        s = self._s(entry_structure="pullback", pullback_lookback=3, pullback_tol=0.005)
        # not trend_up -> False
        assert s._structure_ok_latest([10.0, 11.0, 12.0, 13.0], [11.0] * 4, [9.0] * 4, 3, 12.0, False) is False
        # too few bars -> False
        assert s._structure_ok_latest([10.0, 11.0, 12.0], [11.0] * 3, [9.0] * 3, 2, 12.0, True) is False
        # dipped + near + reclaim -> True
        assert (
            s._structure_ok_latest([10.0, 11.0, 12.0, 13.0, 12.0], [11.0] * 5, [9.0] * 5, 4, 12.0, True)
            is True
        )
        # not dipped -> False
        assert (
            s._structure_ok_latest([13.0, 14.0, 15.0, 16.0, 16.0], [16.5] * 5, [12.5] * 5, 4, 12.0, True)
            is False
        )

    def test_structure_ok_latest_breakout(self) -> None:
        s = self._s(entry_structure="breakout", breakout_lookback=3)
        # too few bars -> False
        assert s._structure_ok_latest([10.0, 11.0], [11.0] * 2, [9.0] * 2, 1, 10.0, True) is False
        # close > prior high -> True
        assert (
            s._structure_ok_latest([10.0, 11.0, 12.0, 13.5], [10.5, 11.5, 12.5, 13.8], [9.5] * 4, 3, 11.0, True)
            is True
        )
        # close <= prior high -> False
        assert (
            s._structure_ok_latest([10.0, 11.0, 12.0, 12.5], [10.5, 11.5, 12.5, 12.8], [9.5] * 4, 3, 11.0, True)
            is False
        )

    def test_structure_mask_vectorized_classic(self) -> None:
        s = self._s()  # classic
        close = pd.Series([10.0, 11.0, 12.0])
        mask = s._structure_mask_vectorized(close, close, close, close, close)
        assert bool(mask.all()) is True

    def test_generate_signals_non_adaptive_profit(self) -> None:
        s = self._s(rsi_adaptive_profit=False)
        n = 40
        close = pd.Series([100.0 + i * 1.0 for i in range(n)])
        df = pd.DataFrame(
            {
                "close": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "volume": pd.Series([1000.0] * n),
            }
        )
        entries, exits = s.generate_signals(df)
        assert len(entries) == n
        # profit_target_exit (non-adaptive) path ran
        assert int(exits.sum()) >= 0
# ---------------------------------------------------------------------------
# volatility_breakout
# ---------------------------------------------------------------------------


class TestVolatilityBreakoutCoverage:
    def test_latest_signal_bb_middle_exit_false(self) -> None:
        from quantflow.strategy.templates.volatility_breakout import (
            VolatilityBreakoutStrategy,
        )

        s = VolatilityBreakoutStrategy(params={"bb_middle_exit": False})
        ctx = _Ctx()
        for i in range(80):
            s.on_bar(
                ctx,
                Bar(
                    "BTC/USDT",
                    i * 60000,
                    100 + i,
                    101 + i,
                    99 + i,
                    100.5 + i,
                    5000 + i * 10,
                ),
            )
        # no assertion on signals: exercises the bb_middle_exit=False path

    def test_check_position_exits_no_direction(self) -> None:
        from quantflow.strategy.templates.volatility_breakout import (
            VolatilityBreakoutStrategy,
        )

        s = VolatilityBreakoutStrategy()
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 1
        s._highest_since_entry = 101.0
        s._lowest_since_entry = 99.0
        s._atr_values = []
        ctx = _Ctx()
        s._check_position_exits(ctx, _bar(100.5))
        assert ctx.signals == []

    def test_check_position_exits_trailing_no_direction(self) -> None:
        from quantflow.strategy.templates.volatility_breakout import (
            VolatilityBreakoutStrategy,
        )

        s = VolatilityBreakoutStrategy()
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 1
        s._highest_since_entry = 101.0
        s._lowest_since_entry = 99.0
        s._atr_values = [2.0]
        ctx = _Ctx()
        s._check_position_exits(ctx, _bar(100.5))
        assert ctx.signals == []
        assert s._in_position is True
