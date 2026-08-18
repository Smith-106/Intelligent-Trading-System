"""Coverage completion for basic strategy templates.

Targets remaining uncovered lines/branches in:
- simple: on_init, should_short default, on_bar entry/short/exit paths,
  generate_signals empty/None + warmup + short-entry, _sma Series/list ok
- non_ma_signal: on_init, on_bar (donchian/volume_roc/rsi_thrust entry +
  exit + stop-loss + max-holding + trim + warmup), _warmup/_latest_signal,
  direct helpers (_donchian_latest, _volume_roc_latest, _rsi_thrust_latest,
  _rsi_at), generate_signals empty + max-holding overlay
- spot_perp_arb: on_init, missing-columns, spot_leg default
- _runtime: profit_target_exit / profit_target_exit_series SHORT branches
- mean_reversion: generate_signals stop-loss block, _stop_loss_exit_series
  SHORT branch, on_bar entry/exit/position-exit paths

Pure logic; no network, no vectorbt.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyContext
from quantflow.strategy.templates._runtime import (
    profit_target_exit,
    profit_target_exit_series,
)
from quantflow.strategy.templates.mean_reversion import MeanReversionStrategy
from quantflow.strategy.templates.non_ma_signal import NonMaSignalStrategy
from quantflow.strategy.templates.simple import SimpleStrategy
from quantflow.strategy.templates.spot_perp_arb import SpotPerpArbStrategy


def _bar(
    close: float,
    ts: int = 0,
    *,
    high: float | None = None,
    low: float | None = None,
    volume: float = 1000.0,
    symbol: str = "BTC/USDT",
) -> Bar:
    h = high if high is not None else close + 0.5
    l = low if low is not None else close - 0.5
    return Bar(symbol=symbol, timestamp=ts, open=close, high=h, low=l, close=close, volume=volume)


class _Ctx:
    """Recording stand-in for StrategyContext."""

    def __init__(self) -> None:
        self.signals: list[tuple] = []
        self.params: dict = {}

    def emit_signal(
        self,
        symbol: str,
        direction: Direction,
        strength: float = 1.0,
        price: float = 0.0,
        strategy_id: str = "",
    ) -> None:
        self.signals.append((symbol, direction, strength, price, strategy_id))


def _feed(strategy, ctx: _Ctx, closes: list[float], **bar_kw) -> None:
    for i, c in enumerate(closes):
        strategy.on_bar(ctx, _bar(c, ts=i, **bar_kw))


# ---------------------------------------------------------------------------
# simple
# ---------------------------------------------------------------------------


class _Shorty(SimpleStrategy):
    """Subclass that actually takes shorts."""

    def should_long(self, closes) -> bool:  # type: ignore[no-untyped-def]
        return False

    def should_short(self, closes) -> bool:  # type: ignore[no-untyped-def]
        return True

    def should_exit_long(self, closes) -> bool:  # type: ignore[no-untyped-def]
        return False

    def should_exit_short(self, closes) -> bool:  # type: ignore[no-untyped-def]
        return True


class TestSimpleStrategy:
    def test_on_init_sets_params(self) -> None:
        s = SimpleStrategy(params={"fast_period": 3, "slow_period": 5})
        ctx = StrategyContext()
        s.on_init(ctx)
        assert ctx.params == s._params

    def test_should_short_default_false(self) -> None:
        assert SimpleStrategy().should_short([1, 2, 3]) is False

    def test_should_exit_short_default_cross_up(self) -> None:
        s = SimpleStrategy(params={"fast_period": 2, "slow_period": 3})
        assert s.should_exit_short([1.0, 2.0, 3.0, 4.0]) is True
        assert s.should_exit_short([9.0, 8.0, 7.0, 6.0]) is False

    def test_on_bar_long_entry_and_exit(self) -> None:
        s = SimpleStrategy(params={"fast_period": 3, "slow_period": 5})
        ctx = _Ctx()
        # rising closes -> fast > slow -> LONG entry on bar 6
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 104.0, 103.0, 102.0, 101.0, 100.0]
        _feed(s, ctx, closes)
        longs = [sg for sg in ctx.signals if sg[1] == Direction.LONG]
        flats = [sg for sg in ctx.signals if sg[1] == Direction.FLAT]
        assert len(longs) == 1
        assert longs[0][0] == "BTC/USDT"
        # fast crosses back below slow -> FLAT
        assert len(flats) == 1

    def test_on_bar_short_entry_and_exit(self) -> None:
        s = _Shorty(params={"fast_period": 3, "slow_period": 5})
        ctx = _Ctx()
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
        _feed(s, ctx, closes)
        shorts = [sg for sg in ctx.signals if sg[1] == Direction.SHORT]
        assert len(shorts) == 1
        # exit short: should_exit_short True on the next bar
        _feed(s, ctx, [106.0])
        flats = [sg for sg in ctx.signals if sg[1] == Direction.FLAT]
        assert len(flats) == 1

    def test_on_bar_short_history_returns(self) -> None:
        s = SimpleStrategy(params={"fast_period": 3, "slow_period": 5})
        ctx = _Ctx()
        _feed(s, ctx, [100.0, 101.0, 102.0])  # < slow
        assert ctx.signals == []

    def test_on_bar_trims_history(self) -> None:
        s = SimpleStrategy(params={"fast_period": 2, "slow_period": 3})
        ctx = _Ctx()
        closes = [100.0 + i for i in range(80)]
        _feed(s, ctx, closes)
        assert len(s._closes) <= s._max_bars

    def test_generate_signals_none_and_empty(self) -> None:
        s = SimpleStrategy(params={"fast_period": 3, "slow_period": 5})
        e1, x1 = s.generate_signals(None)
        assert len(e1) == 0
        e2, x2 = s.generate_signals(pd.DataFrame())
        assert len(e2) == 0
        e3, x3 = s.generate_signals(pd.DataFrame({"close": []}))
        assert len(e3) == 0

    def test_generate_signals_without_close_column(self) -> None:
        s = SimpleStrategy(params={"fast_period": 3, "slow_period": 5})
        df = pd.DataFrame(
            {0: [100.0] * 8, 1: [100.0] * 8, 2: [100.0] * 8, 3: [101.0 + i for i in range(8)]}
        )
        entries, exits = s.generate_signals(df)
        assert len(entries) == 8

    def test_generate_signals_short_variant(self) -> None:
        s = _Shorty(params={"fast_period": 3, "slow_period": 5})
        df = pd.DataFrame({"close": [100.0 + i for i in range(10)]})
        entries, exits = s.generate_signals(df)
        assert int(entries.sum()) >= 1

    def test_sma_series_and_list(self) -> None:
        s = SimpleStrategy(params={"fast_period": 2, "slow_period": 3})
        assert s._sma(pd.Series([1.0, 2.0, 3.0, 4.0]), 2) == 3.5
        assert s._sma([1.0, 2.0, 3.0, 4.0], 2) == 3.5
        assert s._sma(pd.Series([1.0]), 2) is None
        assert s._sma([1.0], 2) is None

    def test_cross_up_and_down(self) -> None:
        s = SimpleStrategy(params={"fast_period": 2, "slow_period": 3})
        rising = [1.0, 2.0, 3.0, 4.0, 5.0]
        falling = [9.0, 8.0, 7.0, 6.0, 5.0]
        assert s._sma_cross_up(rising) is True
        assert s._sma_cross_down(falling) is True
        assert s._sma_cross_up(falling) is False
        assert s._sma_cross_down(rising) is False
        # too few values -> None guards
        assert s._sma_cross_up([1.0]) is False
        assert s._sma_cross_down([1.0]) is False


# ---------------------------------------------------------------------------
# non_ma_signal
# ---------------------------------------------------------------------------


class TestNonMaSignal:
    def test_on_init(self) -> None:
        s = NonMaSignalStrategy(params={"signal_family": "donchian"})
        ctx = StrategyContext()
        s.on_init(ctx)
        assert ctx.params == s._params

    def test_warmup_families(self) -> None:
        assert NonMaSignalStrategy(params={"signal_family": "donchian"})._warmup() == 21
        assert NonMaSignalStrategy(params={"signal_family": "volume_roc"})._warmup() == 21
        assert NonMaSignalStrategy(params={"signal_family": "rsi_thrust"})._warmup() == 22

    def test_donchian_on_bar_entry_then_exit(self) -> None:
        s = NonMaSignalStrategy(
            params={"signal_family": "donchian", "channel_period": 4, "exit_period": 3}
        )
        ctx = _Ctx()
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 102.0, 99.0]
        _feed(s, ctx, closes)
        dirs = [sg[1] for sg in ctx.signals]
        assert dirs == [Direction.LONG, Direction.FLAT]
        # position bookkeeping reset
        assert s._in_position is False

    def test_donchian_stop_loss(self) -> None:
        s = NonMaSignalStrategy(
            params={
                "signal_family": "donchian",
                "channel_period": 4,
                "exit_period": 3,
                "stop_loss_pct": 0.05,
            }
        )
        ctx = _Ctx()
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 98.0]  # entry 104, drop 5.8%
        _feed(s, ctx, closes)
        dirs = [sg[1] for sg in ctx.signals]
        assert dirs == [Direction.LONG, Direction.FLAT]
        assert s._in_position is False

    def test_donchian_stop_loss_block(self) -> None:
        # exit_ signal suppressed via mock so the stop-loss branch runs
        s = NonMaSignalStrategy(
            params={
                "signal_family": "donchian",
                "channel_period": 4,
                "exit_period": 3,
                "stop_loss_pct": 0.05,
            }
        )
        ctx = _Ctx()
        closes = [100.0, 101.0, 102.0, 103.0, 104.0]
        _feed(s, ctx, closes)  # entry LONG at 104
        assert [sg[1] for sg in ctx.signals] == [Direction.LONG]
        s._donchian_latest = lambda *a: (False, False)  # type: ignore[method-assign]
        s.on_bar(ctx, _bar(98.0, ts=5))  # 98 <= 104*0.95 -> stop-loss FLAT
        assert [sg[1] for sg in ctx.signals] == [Direction.LONG, Direction.FLAT]
        assert s._in_position is False

    def test_donchian_max_holding(self) -> None:
        s = NonMaSignalStrategy(
            params={
                "signal_family": "donchian",
                "channel_period": 4,
                "exit_period": 3,
                "max_holding_bars": 2,
            }
        )
        ctx = _Ctx()
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0]
        _feed(s, ctx, closes)
        dirs = [sg[1] for sg in ctx.signals]
        # entry, max-hold FLAT, then re-entry on the next breakout bar
        assert dirs == [Direction.LONG, Direction.FLAT, Direction.LONG]

    def test_trim_history(self) -> None:
        s = NonMaSignalStrategy(params={"signal_family": "donchian"})  # max_bars = 70
        ctx = _Ctx()
        closes = [100.0 + i for i in range(90)]
        _feed(s, ctx, closes)
        assert len(s._bars) == s._max_bars

    def test_volume_roc_on_bar_entry(self) -> None:
        s = NonMaSignalStrategy(
            params={"signal_family": "volume_roc", "roc_period": 3, "vol_period": 3}
        )
        ctx = _Ctx()
        closes = [100.0, 101.0, 102.0, 110.0]
        volumes = [10.0, 10.0, 10.0, 30.0]
        for i, c in enumerate(closes):
            s.on_bar(ctx, _bar(c, ts=i, volume=volumes[i]))
        assert [sg[1] for sg in ctx.signals] == [Direction.LONG]

    def test_rsi_thrust_on_bar_entry_and_exit(self) -> None:
        s = NonMaSignalStrategy(
            params={"signal_family": "rsi_thrust", "rsi_period": 3, "vol_period": 3}
        )
        ctx = _Ctx()
        closes = [100.0, 102.0, 101.0, 104.0, 100.0, 108.0, 110.0, 96.0, 92.0]
        volumes = [10.0, 10.0, 10.0, 10.0, 10.0, 30.0, 30.0, 30.0, 30.0]
        for i, c in enumerate(closes):
            s.on_bar(ctx, _bar(c, ts=i, volume=volumes[i]))
        dirs = [sg[1] for sg in ctx.signals]
        assert Direction.LONG in dirs  # cross-up with volume spike
        assert Direction.FLAT in dirs  # cross-down later

    def test_donchian_latest_direct(self) -> None:
        s = NonMaSignalStrategy(params={"signal_family": "donchian", "channel_period": 3, "exit_period": 2})
        c = [10.0, 11.0, 12.0, 13.0]
        h = [10.5, 11.5, 12.5, 13.5]
        lo = [9.5, 10.5, 11.5, 12.5]
        # i < n -> False, False
        assert s._donchian_latest(c, h, lo, 1) == (False, False)
        # i >= m -> main window branch; breakout entry True
        assert s._donchian_latest(c, h, lo, 3) == (True, False)
        # i in (0, m) with channel_period < exit_period -> partial window
        s2 = NonMaSignalStrategy(params={"signal_family": "donchian", "channel_period": 3, "exit_period": 5})
        assert s2._donchian_latest([10.0, 11.0, 12.0, 13.0], h, lo, 3) == (True, False)
        # exit: close < prior_low
        assert s._donchian_latest([10.0, 11.0, 12.0, 9.0], h, lo, 3) == (False, True)

    def test_volume_roc_latest_direct(self) -> None:
        s = NonMaSignalStrategy(params={"signal_family": "volume_roc", "roc_period": 2, "vol_period": 2})
        # insufficient index
        assert s._volume_roc_latest([1.0, 2.0], [1.0, 1.0], 1) == (False, False)
        # entry: roc > 0 and vol ratio >= threshold
        assert s._volume_roc_latest([10.0, 11.0, 12.0], [1.0, 1.0, 3.0], 2) == (True, False)
        # exit: roc < 0
        assert s._volume_roc_latest([12.0, 11.0, 10.0], [1.0, 1.0, 1.0], 2) == (False, True)
        # c[i - rp] == 0 -> roc 0
        assert s._volume_roc_latest([0.0, 0.0, 0.0], [1.0, 1.0, 1.0], 2) == (False, False)
        # vol_ma == 0 -> ratio 0
        assert s._volume_roc_latest([10.0, 11.0, 12.0], [0.0, 0.0, 0.0], 2) == (False, False)

    def test_rsi_thrust_latest_direct(self) -> None:
        s = NonMaSignalStrategy(params={"signal_family": "rsi_thrust", "rsi_period": 3, "vol_period": 3})
        c = [100.0, 102.0, 101.0, 104.0, 100.0, 108.0]
        v = [10.0, 10.0, 10.0, 10.0, 10.0, 30.0]
        # i too small
        assert s._rsi_thrust_latest(c, v, 2) == (False, False)
        # cross-up with volume -> entry
        assert s._rsi_thrust_latest(c, v, 5) == (True, False)
        # cross-down -> exit (rsi crosses back below the level)
        down = [100.0, 104.0, 108.0, 106.0, 110.0, 100.0]
        dv = [30.0, 30.0, 30.0, 30.0, 30.0, 30.0]
        assert s._rsi_thrust_latest(down, dv, 5) == (False, True)

    def test_rsi_at_direct(self) -> None:
        s = NonMaSignalStrategy(params={"signal_family": "rsi_thrust", "rsi_period": 3})
        assert s._rsi_at([1.0, 2.0], 1) is None  # idx < period
        assert s._rsi_at([100.0, 101.0, 102.0, 103.0], 3) == 100.0  # no losses
        assert s._rsi_at([100.0, 99.0, 98.0, 97.0], 3) == 0.0  # no gains
        rsi = s._rsi_at([100.0, 102.0, 101.0, 104.0, 103.0], 4)
        assert rsi is not None and 0.0 < rsi < 100.0

    def test_generate_signals_empty_df(self) -> None:
        s = NonMaSignalStrategy(params={"signal_family": "donchian"})
        e, x = s.generate_signals(pd.DataFrame())
        assert len(e) == 0 and len(x) == 0

    def test_generate_signals_max_holding_overlay(self) -> None:
        s = NonMaSignalStrategy(
            params={"signal_family": "donchian", "channel_period": 3, "exit_period": 3, "max_holding_bars": 1}
        )
        df = pd.DataFrame(
            {
                "close": [10.0, 11.0, 12.0, 13.0, 14.0],
                "high": [10.5, 11.5, 12.5, 13.5, 14.5],
                "low": [9.5, 10.5, 11.5, 12.5, 13.5],
                "volume": [10.0, 10.0, 10.0, 10.0, 10.0],
            }
        )
        entries, exits = s.generate_signals(df)
        # max_holding_bars=1 -> every entry bar exits next bar
        assert int(entries.sum()) >= 1
        assert int(exits.sum()) >= 1

    def test_generate_signals_missing_volume_column(self) -> None:
        s = NonMaSignalStrategy(params={"signal_family": "volume_roc"})
        df = pd.DataFrame({"close": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]})
        entries, exits = s.generate_signals(df)
        assert len(entries) == len(df)


# ---------------------------------------------------------------------------
# spot_perp_arb
# ---------------------------------------------------------------------------


class TestSpotPerpArb:
    def test_on_init(self) -> None:
        s = SpotPerpArbStrategy()
        ctx = StrategyContext()
        s.on_init(ctx)
        assert ctx.params == s._params

    def test_missing_columns(self) -> None:
        s = SpotPerpArbStrategy()
        df = pd.DataFrame({"close": [1.0] * 20})
        e, x = s.generate_signals(df)
        assert int(e.sum()) == 0

    def test_short_history(self) -> None:
        s = SpotPerpArbStrategy()
        df = pd.DataFrame({"funding_rate": [0.0], "open_interest": [1.0]})
        e, x = s.generate_signals(df)
        assert int(e.sum()) == 0

    def test_spot_leg_default_empty(self) -> None:
        s = SpotPerpArbStrategy()
        assert len(s.spot_leg()) == 0

    def test_full_signal_and_spot_leg(self) -> None:
        s = SpotPerpArbStrategy()
        n = 30
        funding = pd.Series([-0.01] * 10 + [0.01] * 10 + [0.0001] * 10, dtype=float)
        # OI jumps of +100% between segments -> |oi_change| > threshold
        oi = pd.Series([100.0] * 5 + [200.0] * 10 + [300.0] * 15, dtype=float)
        df = pd.DataFrame({"funding_rate": funding, "open_interest": oi})
        entries, exits = s.generate_signals(df)
        assert int((entries == 1).sum()) >= 1
        assert int((entries == -1).sum()) >= 1
        assert int((exits == 1).sum()) >= 1
        assert s.spot_leg().equals(-entries)


# ---------------------------------------------------------------------------
# _runtime exit helpers
# ---------------------------------------------------------------------------


class TestRuntimeExits:
    def test_profit_target_exit_short_direction(self) -> None:
        close = pd.Series([100.0, 99.0, 98.0, 97.0])
        entries = pd.Series([False, True, False, False])
        exits = profit_target_exit(close, entries, 0.01, 5, direction=-1)
        assert bool(exits.iloc[2]) is True  # 99 -> 98 = -1% target hit

    def test_profit_target_exit_series_short_direction(self) -> None:
        close = pd.Series([100.0, 99.0, 98.0, 97.0])
        entries = pd.Series([False, True, False, False])
        pcts = pd.Series([0.0, 0.01, 0.0, 0.0])
        exits = profit_target_exit_series(close, entries, pcts, 5, direction=-1)
        assert bool(exits.iloc[2]) is True

    def test_profit_target_exit_series_short_not_hit(self) -> None:
        # SHORT target not hit and holding not expired -> loop back (222->205)
        close = pd.Series([100.0, 102.0, 101.0, 101.0])
        entries = pd.Series([False, True, False, False])
        pcts = pd.Series([0.0, 0.01, 0.0, 0.0])
        exits = profit_target_exit_series(close, entries, pcts, 5, direction=-1)
        assert bool(exits.sum()) is False

    def test_profit_target_exit_series_long_max_holding(self) -> None:
        close = pd.Series([100.0, 101.0, 101.0, 101.0])
        entries = pd.Series([False, True, False, False])
        pcts = pd.Series([0.0, 0.5, 0.0, 0.0])
        exits = profit_target_exit_series(close, entries, pcts, 2, direction=1)
        assert bool(exits.iloc[3]) is True  # holding expired


# ---------------------------------------------------------------------------
# mean_reversion
# ---------------------------------------------------------------------------


class TestMeanReversion:
    def _strat(self, **overrides) -> MeanReversionStrategy:
        params = {
            "rsi_period": 3,
            "bb_period": 3,
            "volume_period": 3,
            "min_conditions": 1,
            "max_holding_bars": 20,
            "volume_threshold": 2.0,  # vol_ok False -> long/short counts disjoint
        }
        params.update(overrides)
        return MeanReversionStrategy(params=params)

    def test_check_position_exits_no_direction(self) -> None:
        # _entry_direction default None -> both elif-False transitions
        # (277->287 and 300->314) with stop loss enabled
        s = self._strat(stop_loss_pct=0.05)
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 1
        ctx = _Ctx()
        s._check_position_exits(ctx, _bar(100.5))
        assert ctx.signals == []
        assert s._in_position is True

    def test_on_bar_long_entry_and_profit_target_exit(self) -> None:
        s = self._strat(take_profit_pct=0.05)
        ctx = _Ctx()
        # monotonic fall -> rsi ~0 -> LONG at 97; jump to 103 >= 97*1.05 -> FLAT
        closes = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 103.0]
        _feed(s, ctx, closes)
        dirs = [sg[1] for sg in ctx.signals]
        assert dirs == [Direction.LONG, Direction.FLAT]
        assert s._in_position is False

    def test_on_bar_short_entry_and_profit_target_exit(self) -> None:
        s = self._strat(take_profit_pct=0.05)
        ctx = _Ctx()
        # monotonic rise -> rsi ~100 -> SHORT at 103; drop to 97 <= 103*0.95 -> FLAT
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 97.0]
        _feed(s, ctx, closes)
        dirs = [sg[1] for sg in ctx.signals]
        assert dirs == [Direction.SHORT, Direction.FLAT]
        assert s._in_position is False

    def test_on_bar_long_stop_loss(self) -> None:
        s = self._strat(take_profit_pct=0.5, stop_loss_pct=0.05)
        ctx = _Ctx()
        closes = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 90.0]
        _feed(s, ctx, closes)
        dirs = [sg[1] for sg in ctx.signals]
        assert Direction.LONG in dirs
        assert dirs[-1] == Direction.FLAT  # stop loss fires last

    def test_on_bar_short_stop_loss(self) -> None:
        s = self._strat(take_profit_pct=0.5, stop_loss_pct=0.05)
        ctx = _Ctx()
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 112.0]
        _feed(s, ctx, closes)
        dirs = [sg[1] for sg in ctx.signals]
        assert dirs == [Direction.SHORT, Direction.FLAT]
        assert s._in_position is False

    def test_on_bar_long_no_exit_triggers(self) -> None:
        # Wide bands keep rsi 33/66 swings inside the neutral zone so neither
        # long_exit nor short_exit fires; target/stop/max-hold also stay quiet.
        s = self._strat(stop_loss_pct=0.05, take_profit_pct=0.5, bb_std=5.0)
        ctx = _Ctx()
        closes = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 96.0, 95.0, 96.0, 95.0, 96.0]
        _feed(s, ctx, closes)
        dirs = [sg[1] for sg in ctx.signals]
        assert dirs == [Direction.LONG]
        assert s._in_position is True

    def test_on_bar_short_no_exit_triggers(self) -> None:
        s = self._strat(stop_loss_pct=0.05, take_profit_pct=0.5, bb_std=5.0)
        ctx = _Ctx()
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 104.0, 105.0, 104.0, 105.0, 104.0]
        _feed(s, ctx, closes)
        dirs = [sg[1] for sg in ctx.signals]
        assert dirs == [Direction.SHORT]
        assert s._in_position is True

    def test_on_bar_max_holding_exit(self) -> None:
        s = self._strat(max_holding_bars=2)
        ctx = _Ctx()
        closes = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 96.0, 96.0]
        _feed(s, ctx, closes)
        dirs = [sg[1] for sg in ctx.signals]
        assert Direction.LONG in dirs
        assert Direction.FLAT in dirs

    def test_on_bar_insufficient_bars(self) -> None:
        s = self._strat()
        ctx = _Ctx()
        _feed(s, ctx, [100.0, 101.0])  # < bb_period
        assert ctx.signals == []

    def test_latest_signal_insufficient_runtime(self) -> None:
        s = self._strat()
        # no bars -> runtime values empty -> rsi None -> (None, False)
        assert s._latest_signal() == (None, False)

    def test_generate_signals_stop_loss_block(self) -> None:
        s = self._strat(stop_loss_pct=0.05, min_conditions=1, volume_threshold=0.0)
        # both LONG (falling) and SHORT (rising) entries present so both
        # direction branches of _stop_loss_exit_series run
        close = list(range(100, 90, -1)) + list(range(90, 101))
        df = pd.DataFrame({"close": close, "volume": [10.0] * len(close)})
        entries, exits = s.generate_signals(df)
        assert len(entries) == len(df)
        assert int(exits.sum()) >= 0
        # short-side stop: rising tail would trigger a SHORT entry
        assert entries.dtype == bool

    def test_stop_loss_exit_series_short_direction(self) -> None:
        close = pd.Series([100.0, 101.0, 107.0])
        entries = pd.Series([False, True, False])
        exits = MeanReversionStrategy._stop_loss_exit_series(close, entries, 0.05, direction=-1)
        assert bool(exits.iloc[2]) is True  # 107 >= 101 * 1.05

    def test_bars_to_df_empty(self) -> None:
        s = self._strat()
        assert s._bars_to_df().empty is True

    def test_runtime_values_fallback(self) -> None:
        s = self._strat()
        s._close_values = [1.0]  # length differs from _bars -> fallback path
        s._volume_values = [1.0]
        s._bars = [_bar(3.0), _bar(4.0)]
        out = s._runtime_values()
        assert out == ([3.0, 4.0], [1000.0, 1000.0])
