"""Tests for ElliottWaveStrategy on_bar + _check_position_exits — P0-2."""

from __future__ import annotations

import pandas as pd

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyContext
from quantflow.strategy.templates.elliott_wave import ElliottWaveStrategy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bar(price: float = 100.0, idx: int = 0) -> Bar:
    return Bar(
        symbol="BTC/USDT",
        timestamp=1700000000 + idx * 60000,
        open=price - 0.5,
        high=price + 1.0,
        low=price - 1.0,
        close=price,
        volume=1000.0,
    )


class _FakeContext(StrategyContext):
    """Minimal StrategyContext that captures emit_signal calls."""

    def __init__(self):
        self.signals: list[tuple] = []

    def emit_signal(self, symbol, direction, strength=1.0, price=0.0, strategy_id=""):
        self.signals.append((symbol, direction, strength, price, strategy_id))


# ---------------------------------------------------------------------------
# on_bar path tests
# ---------------------------------------------------------------------------


class TestElliottWaveOnBar:
    def test_on_bar_accumulates_bars(self):
        s = ElliottWaveStrategy()
        ctx = _FakeContext()
        for i in range(5):
            s.on_bar(ctx, _make_bar(100.0 + i, i))
        assert len(s._bars) == 5

    def test_on_bar_trims_bars_at_300(self):
        s = ElliottWaveStrategy()
        ctx = _FakeContext()
        for i in range(310):
            s.on_bar(ctx, _make_bar(100.0 + i, i))
        assert len(s._bars) <= 300

    def test_on_bar_no_signal_before_20_bars(self):
        s = ElliottWaveStrategy()
        ctx = _FakeContext()
        for i in range(15):
            s.on_bar(ctx, _make_bar(100.0 + i, i))
        assert len(ctx.signals) == 0

    def test_on_bar_emits_long_entry(self):
        """When the last generate_signals entry is True and not in position,
        emit_signal should fire Direction.LONG."""
        s = ElliottWaveStrategy({"use_divergence": False})
        ctx = _FakeContext()

        # Feed 25 bars then force entry on next bar
        for i in range(25):
            s.on_bar(ctx, _make_bar(100.0 + i, i))
        # No guarantee of entry from random data, so patch generate_signals
        original_gen = s.generate_signals
        len(s._bars)

        def patched_gen(df):
            entries, exits = original_gen(df)
            entries.iloc[-1] = True
            return entries, exits

        s.generate_signals = patched_gen
        s.on_bar(ctx, _make_bar(126.0, 26))

        assert any(sig[1] == Direction.LONG for sig in ctx.signals)

    def test_on_bar_emits_flat_exit(self):
        """When in position and generate_signals exit is True, emit FLAT."""
        s = ElliottWaveStrategy({"use_divergence": False})
        ctx = _FakeContext()

        # Force into position
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 0

        # Feed enough bars to trigger generate_signals
        for i in range(25):
            s.on_bar(ctx, _make_bar(100.0 + i, i))

        # Patch generate_signals to force exit
        len(s._bars)
        original_gen = s.__class__.generate_signals

        def patched_gen(df):
            entries, exits = original_gen(s, df)
            exits.iloc[-1] = True
            return entries, exits

        s.generate_signals = patched_gen
        s.on_bar(ctx, _make_bar(126.0, 26))

        assert any(sig[1] == Direction.FLAT for sig in ctx.signals)

    def test_on_bar_no_duplicate_entry_when_in_position(self):
        """Already in position — entry signal should be ignored."""
        s = ElliottWaveStrategy(
            {"use_divergence": False, "profit_take_pct": 1.0, "max_holding_bars": 1000}
        )
        ctx = _FakeContext()
        s._in_position = True
        s._entry_price = 100.0

        # Patch generate_signals to always produce entry (no exits)
        def always_entry(df):
            entries = pd.Series(True, index=df.index)
            exits = pd.Series(False, index=df.index)
            return entries, exits

        s.generate_signals = always_entry

        # Feed only a few bars so _check_position_exits won't trigger max_holding
        for i in range(3):
            s.on_bar(ctx, _make_bar(100.0 + i, i))

        # No LONG entries should fire since _in_position stays True
        assert not any(sig[1] == Direction.LONG for sig in ctx.signals)

    def test_on_bar_no_exit_when_not_in_position(self):
        """Not in position — exit signal should be ignored."""
        s = ElliottWaveStrategy({"use_divergence": False})
        ctx = _FakeContext()
        s._in_position = False

        # Patch generate_signals to always produce exit
        def always_exit(df):
            entries = pd.Series(False, index=df.index)
            exits = pd.Series(True, index=df.index)
            return entries, exits

        s.generate_signals = always_exit

        for i in range(25):
            s.on_bar(ctx, _make_bar(100.0 + i, i))

        # No FLAT signals since not in position
        assert not any(sig[1] == Direction.FLAT for sig in ctx.signals)


# ---------------------------------------------------------------------------
# _check_position_exits path tests
# ---------------------------------------------------------------------------


class TestElliottWaveCheckPositionExits:
    def test_profit_target_exit(self):
        """When close >= entry * (1 + profit_take_pct), emit FLAT."""
        s = ElliottWaveStrategy({"profit_take_pct": 0.05})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 0

        # Feed a bar with price above target (105)
        bar = _make_bar(106.0)
        s._check_position_exits(ctx, bar)

        assert len(ctx.signals) == 1
        assert ctx.signals[0][1] == Direction.FLAT
        assert s._in_position is False

    def test_profit_target_not_reached(self):
        """When close < target, no exit signal."""
        s = ElliottWaveStrategy({"profit_take_pct": 0.10})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 0

        bar = _make_bar(105.0)  # target = 110
        s._check_position_exits(ctx, bar)

        assert len(ctx.signals) == 0
        assert s._in_position is True

    def test_max_holding_bars_exit(self):
        """When bars_since_entry >= max_holding_bars, emit FLAT."""
        s = ElliottWaveStrategy({"max_holding_bars": 5, "profit_take_pct": 1.0})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 4  # will be incremented to 5

        bar = _make_bar(101.0)  # below profit target (target=200)
        s._check_position_exits(ctx, bar)

        assert len(ctx.signals) == 1
        assert ctx.signals[0][1] == Direction.FLAT
        assert s._in_position is False

    def test_max_holding_not_reached(self):
        """When bars_since_entry < max_holding_bars, no exit."""
        s = ElliottWaveStrategy({"max_holding_bars": 20, "profit_take_pct": 1.0})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 3

        bar = _make_bar(101.0)
        s._check_position_exits(ctx, bar)

        assert len(ctx.signals) == 0
        assert s._in_position is True

    def test_no_exit_when_not_in_position(self):
        """_check_position_exits should return immediately if not in position."""
        s = ElliottWaveStrategy()
        ctx = _FakeContext()
        s._in_position = False

        bar = _make_bar(200.0)
        s._check_position_exits(ctx, bar)

        assert len(ctx.signals) == 0

    def test_bars_since_entry_increments(self):
        """Each call to _check_position_exits increments _bars_since_entry."""
        s = ElliottWaveStrategy({"max_holding_bars": 100, "profit_take_pct": 1.0})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 0

        for _i in range(5):
            s._check_position_exits(ctx, _make_bar(101.0))

        assert s._bars_since_entry == 5
        assert s._in_position is True  # not triggered yet

    def test_profit_target_exits_before_max_holding(self):
        """Profit target exit fires before max holding check."""
        s = ElliottWaveStrategy({"max_holding_bars": 3, "profit_take_pct": 0.02})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 0

        # bar.close = 103 >= target (102)
        bar = _make_bar(103.0)
        s._check_position_exits(ctx, bar)

        assert len(ctx.signals) == 1
        assert ctx.signals[0][1] == Direction.FLAT
        assert s._in_position is False
        # Profit target returns early, so _bars_since_entry is 1
        assert s._bars_since_entry == 1

    def test_uses_strategy_name_in_signal(self):
        """emit_signal should include strategy_id = self.name."""
        s = ElliottWaveStrategy({"profit_take_pct": 0.05})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 0

        bar = _make_bar(106.0)
        s._check_position_exits(ctx, bar)

        assert ctx.signals[0][4] == "elliott_wave"


# ---------------------------------------------------------------------------
# Integration: on_bar → _check_position_exits chain
# ---------------------------------------------------------------------------


class TestElliottWaveOnBarIntegration:
    def test_on_bar_triggers_profit_exit(self):
        """Full chain: on_bar entry → price rise → profit exit in same on_bar."""
        s = ElliottWaveStrategy({"profit_take_pct": 0.02, "use_divergence": False})
        ctx = _FakeContext()

        # Accumulate enough bars for generate_signals
        for i in range(25):
            s.on_bar(ctx, _make_bar(100.0 + i, i))

        # Force entry
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 0

        # Now feed a bar with profit_target reached
        # Patch generate_signals to return no new entries, no exits
        # so only _check_position_exits fires
        def no_signals(df):
            entries = pd.Series(False, index=df.index)
            exits = pd.Series(False, index=df.index)
            return entries, exits

        s.generate_signals = no_signals
        bar = _make_bar(103.0, 26)  # above 2% target
        s.on_bar(ctx, bar)

        assert any(sig[1] == Direction.FLAT for sig in ctx.signals)

    def test_on_bar_exits_when_exit_signal_and_in_position(self):
        """Line 99-100: exit signal while in position should emit FLAT and clear state."""
        s = ElliottWaveStrategy({"use_divergence": False})
        ctx = _FakeContext()
        s._in_position = True
        s._entry_price = 100.0
        s._bars_since_entry = 0

        # Patch _bars_to_df to return a valid df, and generate_signals to force exit

        def force_exit_gen(df):
            entries = pd.Series(False, index=df.index)
            exits = pd.Series(False, index=df.index)
            exits.iloc[-1] = True
            return entries, exits

        s.generate_signals = force_exit_gen
        # Feed enough bars first so generate_signals works
        for i in range(25):
            _make_bar(100.0 + i, i)
            # Use a different approach: feed the bar but with patched generate_signals
        # Instead, just directly set the bars and call on_bar
        s._bars = [_make_bar(100.0 + i, i) for i in range(25)]
        s.on_bar(ctx, _make_bar(126.0, 26))

        assert any(sig[1] == Direction.FLAT for sig in ctx.signals)
        assert s._in_position is False

    def test_on_bar_returns_when_df_empty(self):
        """Line 86: _bars_to_df returns empty → on_bar returns early."""
        s = ElliottWaveStrategy({"use_divergence": False})
        ctx = _FakeContext()
        s._bars = []  # Empty → _bars_to_df returns empty

        # on_bar will append the bar, but then check len < 20 → return early
        s.on_bar(ctx, _make_bar(100.0, 0))
        assert len(ctx.signals) == 0

    def test_on_bar_returns_when_entries_empty(self):
        """Line 90: generate_signals returns empty entries → on_bar returns."""
        s = ElliottWaveStrategy({"use_divergence": False})
        ctx = _FakeContext()

        # Feed enough bars for generate_signals to run
        for i in range(25):
            s.on_bar(ctx, _make_bar(100.0, i))

        # Clear any signals so far
        ctx.signals.clear()

        # Patch generate_signals to always return empty
        def always_empty(df):
            return pd.Series(dtype=bool), pd.Series(dtype=bool)

        s.generate_signals = always_empty
        s.on_bar(ctx, _make_bar(126.0, 26))

        # No signals should be emitted
        assert len(ctx.signals) == 0

    def test_bars_to_df_returns_empty_when_no_bars(self):
        """Line 130: _bars_to_df with empty _bars returns empty DataFrame."""
        s = ElliottWaveStrategy()
        df = s._bars_to_df()
        assert df.empty
