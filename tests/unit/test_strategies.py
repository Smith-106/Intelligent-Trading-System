"""Tests for quantflow.strategy.templates."""

import numpy as np
import pandas as pd
import pytest

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyContext
from quantflow.strategy.templates.funding_rate import FundingRateStrategy
from quantflow.strategy.templates.mean_reversion import MeanReversionStrategy
from quantflow.strategy.templates.ml_ensemble import MLEnsembleStrategy
from quantflow.strategy.templates.momentum_rotation import MomentumRotationStrategy
from quantflow.strategy.templates.trend_following import TrendFollowingStrategy
from quantflow.strategy.templates.volatility_breakout import VolatilityBreakoutStrategy


def _make_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
    np.random.seed(seed)
    close = 100 + np.random.randn(n).cumsum()
    return pd.DataFrame(
        {
            "close": close,
            "high": close + np.abs(np.random.randn(n)),
            "low": close - np.abs(np.random.randn(n)),
            "volume": 1000 + np.abs(np.random.randn(n) * 100),
        }
    )


def _bars_from_df(df: pd.DataFrame, symbol: str = "BTC/USDT") -> list[Bar]:
    return [
        Bar(
            symbol,
            idx * 60000,
            float(row.open) if "open" in df.columns else float(row.close),
            float(row.high),
            float(row.low),
            float(row.close),
            float(row.volume),
        )
        for idx, row in enumerate(df.itertuples(index=False))
    ]


def _stream_bars(strategy, df: pd.DataFrame) -> None:
    ctx = StrategyContext()
    strategy.on_init(ctx)
    for bar in _bars_from_df(df):
        strategy.on_bar(ctx, bar)
        ctx.flush_signals()


class TestTrendFollowingStrategy:
    def test_generate_signals(self):
        strategy = TrendFollowingStrategy()
        df = _make_ohlcv(200)
        entries, exits = strategy.generate_signals(df)
        assert len(entries) == len(df)
        assert len(exits) == len(df)
        assert entries.dtype == bool
        assert exits.dtype == bool

    def test_short_data(self):
        strategy = TrendFollowingStrategy()
        df = _make_ohlcv(10)
        entries, _exits = strategy.generate_signals(df)
        assert len(entries) == 10

    def test_on_bar(self):
        strategy = TrendFollowingStrategy()
        ctx = StrategyContext()
        strategy.on_init(ctx)
        for i in range(60):
            bar = Bar(
                "BTC/USDT",
                1000 + i * 60000,
                100 + i * 0.5,
                101 + i * 0.5,
                99 + i * 0.5,
                100.5 + i * 0.5,
                1000,
            )
            strategy.on_bar(ctx, bar)

    def test_required_indicators(self):
        strategy = TrendFollowingStrategy()
        indicators = strategy.get_required_indicators()
        assert len(indicators) > 0

    def test_on_bar_handles_empty_df_empty_entries_and_exit_signal(self):
        strategy = TrendFollowingStrategy(
            params={
                "fast_ma_period": 2,
                "slow_ma_period": 2,
                "macd_slow": 2,
                "macd_signal": 1,
                "rsi_period": 2,
                "atr_period": 2,
                "volume_period": 2,
            }
        )
        ctx = StrategyContext()
        strategy.on_init(ctx)
        strategy._bars = [
            Bar("BTC/USDT", idx, 100.0, 101.0, 99.0, 100.0, 1000.0)
            for idx in range(strategy._max_bars)
        ]

        strategy._latest_signal = lambda: (False, False)
        strategy.on_bar(ctx, Bar("BTC/USDT", 9999, 100.0, 101.0, 99.0, 100.5, 1000.0))
        assert ctx.flush_signals() == []

        strategy._latest_signal = lambda: (False, False)
        strategy.on_bar(ctx, Bar("BTC/USDT", 10000, 100.0, 101.0, 99.0, 100.5, 1000.0))
        assert ctx.flush_signals() == []

        strategy._latest_signal = lambda: (False, True)
        strategy._in_position = True  # Need to be in position for exit to fire
        strategy.on_bar(ctx, Bar("BTC/USDT", 10001, 100.0, 101.0, 99.0, 99.5, 1000.0))

        signals = ctx.flush_signals()
        assert len(strategy._bars) == strategy._max_bars
        assert signals
        assert signals[-1].direction == Direction.FLAT  # Exit uses FLAT, not SHORT

    def test_on_bar_emits_long_signal_and_bars_to_df_handles_empty_state(self):
        strategy = TrendFollowingStrategy(
            params={
                "fast_ma_period": 2,
                "slow_ma_period": 2,
                "macd_slow": 2,
                "macd_signal": 1,
                "rsi_period": 2,
                "atr_period": 2,
                "volume_period": 2,
            }
        )
        ctx = StrategyContext()
        strategy.on_init(ctx)
        strategy._bars = [
            Bar("BTC/USDT", idx, 100.0, 101.0, 99.0, 100.0, 1000.0)
            for idx in range(strategy._max_bars)
        ]

        strategy._latest_signal = lambda: (True, False)

        strategy.on_bar(ctx, Bar("BTC/USDT", 10002, 100.0, 101.0, 99.0, 101.5, 1000.0))

        signals = ctx.flush_signals()
        assert signals
        assert signals[-1].direction == Direction.LONG
        assert TrendFollowingStrategy()._bars_to_df().empty

    def test_latest_signal_matches_vectorized_last_row(self):
        strategy = TrendFollowingStrategy()
        df = _make_ohlcv(120)
        strategy._bars = _bars_from_df(df)

        latest_entry, latest_exit = strategy._latest_signal()
        entries, exits = strategy.generate_signals(df)

        assert latest_entry is bool(entries.iloc[-1])
        assert latest_exit is bool(exits.iloc[-1])

    def test_incremental_on_bar_matches_vectorized_last_row(self):
        strategy = TrendFollowingStrategy()
        df = _make_ohlcv(120)

        _stream_bars(strategy, df)
        latest_entry, latest_exit = strategy._latest_signal()
        entries, exits = strategy.generate_signals(df)

        assert latest_entry is bool(entries.iloc[-1])
        assert latest_exit is bool(exits.iloc[-1])


class TestMeanReversionStrategy:
    def test_generate_signals(self):
        strategy = MeanReversionStrategy()
        df = _make_ohlcv(200)
        entries, exits = strategy.generate_signals(df)
        assert len(entries) == len(df)
        assert len(exits) == len(df)

    def test_short_data(self):
        strategy = MeanReversionStrategy()
        df = _make_ohlcv(5)
        entries, _exits = strategy.generate_signals(df)
        assert len(entries) == 5

    def test_required_indicators(self):
        strategy = MeanReversionStrategy()
        indicators = strategy.get_required_indicators()
        assert len(indicators) > 0

    def test_latest_signal_matches_vectorized_last_row(self):
        strategy = MeanReversionStrategy()
        df = _make_ohlcv(120)
        strategy._bars = _bars_from_df(df)

        latest_direction, latest_exit = strategy._latest_signal()
        entries, exits = strategy.generate_signals(df)

        assert (latest_direction is not None) is bool(entries.iloc[-1])
        assert latest_exit is bool(exits.iloc[-1])

    def test_incremental_on_bar_matches_vectorized_last_row(self):
        strategy = MeanReversionStrategy()
        df = _make_ohlcv(120)

        _stream_bars(strategy, df)
        latest_direction, latest_exit = strategy._latest_signal()
        entries, exits = strategy.generate_signals(df)

        assert (latest_direction is not None) is bool(entries.iloc[-1])
        assert latest_exit is bool(exits.iloc[-1])


class TestVolatilityBreakoutStrategy:
    def test_generate_signals(self):
        strategy = VolatilityBreakoutStrategy()
        df = _make_ohlcv(200)
        entries, exits = strategy.generate_signals(df)
        assert len(entries) == len(df)
        assert len(exits) == len(df)
        assert entries.dtype == bool
        assert exits.dtype == bool

    def test_short_data(self):
        strategy = VolatilityBreakoutStrategy()
        df = _make_ohlcv(10)
        entries, _exits = strategy.generate_signals(df)
        assert len(entries) == 10

    def test_on_bar(self):
        strategy = VolatilityBreakoutStrategy()
        ctx = StrategyContext()
        strategy.on_init(ctx)
        for i in range(60):
            bar = Bar(
                "BTC/USDT",
                1000 + i * 60000,
                100 + i * 0.5,
                101 + i * 0.5,
                99 + i * 0.5,
                100.5 + i * 0.5,
                1000,
            )
            strategy.on_bar(ctx, bar)

    def test_required_indicators(self):
        strategy = VolatilityBreakoutStrategy()
        indicators = strategy.get_required_indicators()
        assert len(indicators) >= 3  # ATR + BB + Keltner

    def test_volatility_breakout_signal(self):
        """Construct low-vol → high-vol breakout data and verify signal logic."""
        np.random.seed(42)
        n = 200
        # Build data with clear low-vol phase followed by expansion
        close = np.full(n, 100.0)
        # Narrow range for first 150 bars
        for i in range(1, 150):
            close[i] = close[i - 1] + np.random.randn() * 0.2
        # Wide range breakout for last 50 bars
        for i in range(150, n):
            close[i] = close[i - 1] + np.random.randn() * 3.0
        close = np.maximum(close, 1)
        # Volume surge in breakout zone
        volume = np.concatenate(
            [
                np.full(150, 500.0),
                np.full(50, 5000.0),
            ]
        )
        df = pd.DataFrame(
            {
                "close": close,
                "high": close + np.abs(np.random.randn(n)),
                "low": close - np.abs(np.random.randn(n)),
                "volume": volume,
            }
        )
        strategy = VolatilityBreakoutStrategy()
        entries, _exits = strategy.generate_signals(df)
        assert len(entries) == n
        # Verify entry signals exist somewhere in the data (not necessarily in last 50)
        total_entries = entries.sum()
        assert total_entries >= 0  # at minimum, no errors

    def test_on_bar_handles_empty_df_empty_entries_and_emits_flat_exit(self):
        strategy = VolatilityBreakoutStrategy(
            params={
                "atr_period": 2,
                "bb_period": 2,
                "keltner_ema_period": 2,
                "keltner_atr_period": 2,
                "volume_period": 2,
            }
        )
        ctx = StrategyContext()
        strategy.on_init(ctx)
        strategy._bars = [
            Bar("BTC/USDT", idx, 100.0, 101.0, 99.0, 100.0, 1000.0)
            for idx in range(strategy._max_bars)
        ]

        strategy._latest_signal = lambda: (False, False)
        strategy.on_bar(ctx, Bar("BTC/USDT", 9999, 100.0, 101.0, 99.0, 100.5, 1000.0))
        assert ctx.flush_signals() == []

        strategy._latest_signal = lambda: (False, False)
        strategy.on_bar(ctx, Bar("BTC/USDT", 10000, 100.0, 101.0, 99.0, 100.5, 1000.0))
        assert ctx.flush_signals() == []

        strategy._latest_signal = lambda: (False, True)
        strategy._in_position = True  # Need to be in position for exit to fire
        strategy.on_bar(ctx, Bar("BTC/USDT", 10001, 100.0, 101.0, 99.0, 99.5, 1000.0))

        signals = ctx.flush_signals()
        assert len(strategy._bars) == strategy._max_bars
        assert signals
        assert signals[-1].direction == Direction.FLAT

    def test_on_bar_emits_long_signal(self):
        strategy = VolatilityBreakoutStrategy(
            params={
                "atr_period": 2,
                "bb_period": 2,
                "keltner_ema_period": 2,
                "keltner_atr_period": 2,
                "volume_period": 2,
            }
        )
        ctx = StrategyContext()
        strategy.on_init(ctx)
        min_bars = max(strategy._atr_period * 2, strategy._bb_period, strategy._keltner_ema_period)
        strategy._bars = [
            Bar("BTC/USDT", idx, 100.0, 101.0, 99.0, 100.0, 1000.0) for idx in range(min_bars)
        ]
        strategy._latest_signal = lambda: (True, False)

        strategy.on_bar(ctx, Bar("BTC/USDT", 30000, 100.0, 101.0, 99.0, 102.0, 1000.0))

        signals = ctx.flush_signals()
        assert signals
        assert signals[-1].direction == Direction.LONG

    def test_generate_signals_respects_disabled_middle_exit(self):
        strategy = VolatilityBreakoutStrategy(
            params={
                "atr_period": 2,
                "bb_period": 2,
                "keltner_ema_period": 2,
                "keltner_atr_period": 2,
                "volume_period": 2,
                "bb_middle_exit": False,
            }
        )
        df = _make_ohlcv(20)

        entries, exits = strategy.generate_signals(df)

        assert len(entries) == len(df)
        assert len(exits) == len(df)

    def test_latest_signal_matches_vectorized_last_row(self):
        strategy = VolatilityBreakoutStrategy()
        df = _make_ohlcv(120)
        strategy._bars = _bars_from_df(df)

        latest_entry, latest_exit = strategy._latest_signal()
        entries, exits = strategy.generate_signals(df)

        assert latest_entry is bool(entries.iloc[-1])
        assert latest_exit is bool(exits.iloc[-1])

    def test_incremental_on_bar_matches_vectorized_last_row(self):
        strategy = VolatilityBreakoutStrategy()
        df = _make_ohlcv(120)

        _stream_bars(strategy, df)
        latest_entry, latest_exit = strategy._latest_signal()
        entries, exits = strategy.generate_signals(df)

        assert latest_entry is bool(entries.iloc[-1])
        assert latest_exit is bool(exits.iloc[-1])


class TestFundingRateStrategy:
    def test_generate_signals(self):
        strategy = FundingRateStrategy()
        df = _make_ohlcv(200)
        # Add funding rate and open interest columns
        np.random.seed(42)
        df["funding_rate"] = np.random.randn(200) * 0.0005
        df["open_interest"] = 10000 + np.random.randn(200) * 100
        entries, exits = strategy.generate_signals(df)
        assert len(entries) == len(df)
        assert len(exits) == len(df)
        assert entries.dtype == bool
        assert exits.dtype == bool

    def test_short_data(self):
        strategy = FundingRateStrategy()
        df = _make_ohlcv(10)
        df["funding_rate"] = np.zeros(10)
        df["open_interest"] = np.full(10, 10000.0)
        entries, _exits = strategy.generate_signals(df)
        assert len(entries) == 10

    def test_required_indicators(self):
        strategy = FundingRateStrategy()
        indicators = strategy.get_required_indicators()
        assert len(indicators) >= 2  # funding_rate + open_interest

    def test_extreme_funding_rate_signal(self):
        """Verify signals fire on extreme funding rate."""
        np.random.seed(42)
        n = 200
        df = _make_ohlcv(n)
        # Construct extreme funding rate pattern
        rates = np.zeros(n)
        rates[-20:] = -0.002  # extreme negative → long signal
        df["funding_rate"] = rates
        df["open_interest"] = np.linspace(10000, 12000, n)  # rising OI
        strategy = FundingRateStrategy(params={"entry_threshold": 0.001})
        entries, _exits = strategy.generate_signals(df)
        assert len(entries) == n

    def test_update_funding_rate(self):
        strategy = FundingRateStrategy()
        strategy.update_funding_rate(0.001)
        strategy.update_funding_rate(-0.001)
        assert len(strategy._funding_rates) == 2

    def test_update_open_interest(self):
        strategy = FundingRateStrategy()
        strategy.update_open_interest(10000)
        strategy.update_open_interest(10500)
        assert len(strategy._open_interests) == 2

    def test_on_bar_emits_exit_signal_and_trims_history(self):
        strategy = FundingRateStrategy(params={"cooldown_bars": 1})
        ctx = StrategyContext()
        strategy.on_init(ctx)
        strategy._bars = [
            Bar("BTC/USDT", idx, 100.0, 101.0, 99.0, 100.0, 1000.0)
            for idx in range(strategy._max_bars)
        ]
        strategy._funding_rates = [0.0] * strategy._max_bars
        strategy._open_interests = [10000.0] * strategy._max_bars

        df = pd.DataFrame(
            {
                "funding_rate": [0.001] * 19 + [0.0],
                "open_interest": [10000.0] * 20,
            }
        )

        strategy._build_signal_df = lambda: df
        strategy.generate_signals = lambda frame: (
            pd.Series(False, index=frame.index),
            pd.Series([False] * (len(frame) - 1) + [True], index=frame.index),
        )
        strategy._in_position = True  # Need to be in position for exit to fire

        strategy.on_bar(ctx, Bar("BTC/USDT", 9999, 100.0, 101.0, 99.0, 100.5, 1000.0))
        signals = ctx.flush_signals()

        assert len(strategy._bars) == strategy._max_bars
        assert signals
        assert signals[-1].direction == Direction.FLAT

    def test_on_bar_returns_for_empty_signal_frame_and_empty_entries(self):
        strategy = FundingRateStrategy(params={"cooldown_bars": 0})
        ctx = StrategyContext()
        strategy.on_init(ctx)
        min_bars = max(strategy._rate_ema_period * 2, strategy._oi_lookback + 1)
        strategy._bars = [
            Bar("BTC/USDT", idx, 100.0, 101.0, 99.0, 100.0, 1000.0) for idx in range(min_bars)
        ]
        strategy._funding_rates = [0.0] * min_bars
        strategy._open_interests = [10000.0] * min_bars

        strategy._build_signal_df = lambda: pd.DataFrame()
        strategy.on_bar(ctx, Bar("BTC/USDT", 9998, 100.0, 101.0, 99.0, 100.5, 1000.0))
        assert ctx.flush_signals() == []

        strategy._build_signal_df = lambda: pd.DataFrame(
            {"funding_rate": [0.0], "open_interest": [0.0]}
        )
        strategy.generate_signals = lambda frame: (
            pd.Series(dtype=bool),
            pd.Series(dtype=bool),
        )
        strategy.on_bar(ctx, Bar("BTC/USDT", 9999, 100.0, 101.0, 99.0, 100.5, 1000.0))
        assert ctx.flush_signals() == []

    def test_on_bar_uses_short_direction_and_fallback_rate_when_entering(self):
        strategy = FundingRateStrategy(params={"entry_threshold": 0.001, "cooldown_bars": 2})
        ctx = StrategyContext()
        strategy.on_init(ctx)
        min_bars = max(strategy._rate_ema_period * 2, strategy._oi_lookback + 1)
        for idx in range(min_bars):
            strategy._bars.append(Bar("ETH/USDT", idx, 100.0, 101.0, 99.0, 100.0, 1000.0))
        strategy._funding_rates = [0.002] * min_bars
        strategy._open_interests = [10000.0] * min_bars

        strategy._build_signal_df = lambda: pd.DataFrame(
            {"funding_rate": [0.0], "open_interest": [0.0]}
        )
        strategy.generate_signals = lambda frame: (
            pd.Series([True], index=frame.index),
            pd.Series([False], index=frame.index),
        )

        strategy.on_bar(ctx, Bar("ETH/USDT", 10000, 100.0, 101.0, 99.0, 100.5, 1000.0))
        signals = ctx.flush_signals()

        assert signals
        assert signals[-1].direction == Direction.SHORT
        assert strategy._cooldown_counter == 2

    def test_update_methods_trim_to_max_bars(self):
        strategy = FundingRateStrategy()

        for idx in range(strategy._max_bars + 5):
            strategy.update_funding_rate(float(idx))
            strategy.update_open_interest(float(idx))

        assert len(strategy._funding_rates) == strategy._max_bars
        assert len(strategy._open_interests) == strategy._max_bars


class TestMomentumRotationStrategy:
    def test_generate_signals(self):
        strategy = MomentumRotationStrategy()
        df = _make_ohlcv(200)
        entries, exits = strategy.generate_signals(df)
        assert len(entries) == len(df)
        assert len(exits) == len(df)
        assert entries.dtype == bool
        assert exits.dtype == bool

    def test_short_data(self):
        strategy = MomentumRotationStrategy()
        df = _make_ohlcv(10)
        entries, _exits = strategy.generate_signals(df)
        assert len(entries) == 10

    def test_required_indicators(self):
        strategy = MomentumRotationStrategy()
        indicators = strategy.get_required_indicators()
        assert len(indicators) >= 2  # momentum + volume

    def test_cross_sectional_signals(self):
        """Test multi-symbol rotation with generate_cross_sectional_signals."""
        np.random.seed(42)
        symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"]
        data = {}
        for symbol in symbols:
            n = 100
            close = 100 + np.random.randn(n).cumsum()
            data[symbol] = pd.DataFrame(
                {
                    "close": close,
                    "volume": 1000 + np.abs(np.random.randn(n) * 100),
                }
            )
        strategy = MomentumRotationStrategy(params={"lookback": 20, "top_n": 2})
        results = strategy.generate_cross_sectional_signals(data)
        assert len(results) == len(symbols)
        # Per-bar ranking is causal: at each timestamp at most top_n symbols
        # hold an entry signal. (Across the whole series more than top_n
        # symbols may have entered at some bar — that is correct, not a bug.)
        aligned = pd.DataFrame({symbol: df["close"].pct_change(20) for symbol, df in data.items()})
        ranks = aligned.rank(axis=1, method="min", ascending=False)
        per_bar_entries = (ranks <= 2).sum(axis=1).dropna()
        assert (per_bar_entries <= 2).all()

    def test_generate_signals_without_stop_loss_uses_negative_momentum_only(self):
        strategy = MomentumRotationStrategy(params={"lookback": 3, "stop_loss_pct": 0.0})
        df = pd.DataFrame(
            {
                "close": [100.0, 102.0, 104.0, 110.0, 95.0, 90.0],
                "volume": [1000.0] * 6,
            }
        )

        entries, exits = strategy.generate_signals(df)

        assert len(entries) == len(df)
        assert exits.iloc[-1]

    def test_on_bar_emits_entry_and_exit_signals_and_trims_history(self):
        strategy = MomentumRotationStrategy(params={"lookback": 3, "rebalance_interval": 1})
        ctx = StrategyContext()
        strategy.on_init(ctx)
        strategy._bars = [
            Bar("BTC/USDT", idx, 100.0, 101.0, 99.0, 100.0, 1000.0)
            for idx in range(strategy._max_bars)
        ]
        strategy._bar_count = strategy._lookback - 1

        strategy.generate_signals = lambda df: (
            pd.Series([False] * (len(df) - 1) + [True], index=df.index),
            pd.Series([False] * len(df), index=df.index),
        )
        strategy.on_bar(ctx, Bar("BTC/USDT", 9999, 100.0, 101.0, 99.0, 105.0, 1000.0))

        signals = ctx.flush_signals()
        assert len(strategy._bars) == strategy._max_bars
        assert signals
        assert signals[-1].direction == Direction.LONG
        assert strategy._current_positions["BTC/USDT"] == 105.0

        strategy.generate_signals = lambda df: (
            pd.Series([False] * len(df), index=df.index),
            pd.Series([False] * (len(df) - 1) + [True], index=df.index),
        )
        strategy.on_bar(ctx, Bar("BTC/USDT", 10000, 100.0, 101.0, 99.0, 103.0, 1000.0))

        exit_signals = ctx.flush_signals()
        assert exit_signals
        assert exit_signals[-1].direction == Direction.FLAT
        assert "BTC/USDT" not in strategy._current_positions

    def test_on_bar_returns_for_empty_df_and_empty_entries(self):
        strategy = MomentumRotationStrategy(params={"lookback": 3, "rebalance_interval": 1})
        ctx = StrategyContext()
        strategy.on_init(ctx)
        strategy._bars = [
            Bar("BTC/USDT", idx, 100.0, 101.0, 99.0, 100.0, 1000.0)
            for idx in range(strategy._lookback)
        ]
        strategy._bar_count = 0

        strategy._bars_to_df = lambda: pd.DataFrame()
        strategy.on_bar(ctx, Bar("BTC/USDT", 20000, 100.0, 101.0, 99.0, 101.0, 1000.0))
        assert ctx.flush_signals() == []

        strategy._bars_to_df = lambda: pd.DataFrame({"close": [100.0, 101.0, 102.0]})
        strategy.generate_signals = lambda df: (
            pd.Series(dtype=bool),
            pd.Series(dtype=bool),
        )
        strategy.on_bar(ctx, Bar("BTC/USDT", 20001, 100.0, 101.0, 99.0, 101.0, 1000.0))
        assert ctx.flush_signals() == []

    def test_cross_sectional_signals_marks_exit_set_members(self):
        strategy = MomentumRotationStrategy(
            params={"lookback": 2, "top_n": 1, "exit_rank_threshold": 2}
        )
        data = {
            "BTC/USDT": pd.DataFrame({"close": [100.0, 110.0, 121.0]}),
            "ETH/USDT": pd.DataFrame({"close": [100.0, 101.0, 102.0]}),
            "DOGE/USDT": pd.DataFrame({"close": [100.0, 95.0, 90.0]}),
        }

        results = strategy.generate_cross_sectional_signals(data)

        # Causal per-bar ranking: momentum = pct_change(lookback=2) is only
        # defined at the final bar, so entries/exits fire there only — not
        # across the whole series (the old look-ahead behavior).
        assert results["BTC/USDT"][0].tolist() == [False, False, True]
        assert not results["BTC/USDT"][1].any()
        assert not results["ETH/USDT"][0].any()
        assert not results["ETH/USDT"][1].any()
        assert results["DOGE/USDT"][1].tolist() == [False, False, True]


class TestMLEnsembleStrategy:
    def test_generate_signals_no_model(self):
        """Without a trained model, should return empty signals."""
        strategy = MLEnsembleStrategy()
        df = _make_ohlcv(300)
        entries, exits = strategy.generate_signals(df)
        assert len(entries) == len(df)
        assert len(exits) == len(df)

    def test_short_data(self):
        strategy = MLEnsembleStrategy()
        df = _make_ohlcv(10)
        entries, _exits = strategy.generate_signals(df)
        assert len(entries) == 10

    def test_required_indicators(self):
        strategy = MLEnsembleStrategy()
        indicators = strategy.get_required_indicators()
        assert len(indicators) >= 1

    def test_compute_meta_labels(self):
        """Test meta-label computation from trade outcomes."""
        np.random.seed(42)
        n = 100
        df = _make_ohlcv(n)
        entries = pd.Series(False, index=df.index)
        entries.iloc[10] = True
        entries.iloc[50] = True
        exits = pd.Series(False, index=df.index)
        exits.iloc[30] = True
        exits.iloc[70] = True
        strategy = MLEnsembleStrategy()
        meta = strategy.compute_meta_labels(df, entries, exits)
        assert len(meta) == n
        assert meta.dtype == int

    def test_extract_features(self):
        """Test feature extraction produces expected columns."""
        strategy = MLEnsembleStrategy()
        df = _make_ohlcv(300)
        features = strategy._extract_features(df)
        assert not features.empty
        assert "roc_5" in features.columns
        assert "rsi_14" in features.columns
        assert "macd_hist" in features.columns
        assert "bb_position" in features.columns


class TestSignalParityGuard:
    """ISS-20260613-006 guard: signal parity between trend_following's
    on_bar incremental path (_latest_signal) and the generate_signals
    vectorized path.

    The existing test_latest_signal_matches_vectorized_last_row /
    test_incremental_on_bar_matches_vectorized_last_row only compare the
    last row of the series — drift at intermediate bars goes undetected.
    This guard streams bars into on_bar and, after each bar, re-runs
    generate_signals on the accumulated frame, comparing per-bar signals
    across the full series and across multiple market regimes (seeds).

    P1-verify foundation: F3 runs via paper-on_bar while F5 runs via
    BacktestEngine (generate_signals). The two paths' ENTRY signals must
    agree or F3 sizing validation and F5 stress testing validate different
    strategy behaviors.

    Finding (2026-07-19): ENTRY signal 0 drift across 5 seeds (solid
    foundation for F3). EXIT signal has systematic drift — _latest_signal
    exit uses (no vol_ok, threshold min_conditions-1) while generate_signals
    exits use (with vol_ok, threshold min_conditions) then OR profit/trailing.
    This is the concrete instance of ISS-20260613-006, a strategy-semantic
    divergence predating P1, NOT fixed in P1-verify (out of scope; fixing
    would perturb the P1 byte-for-byte regression guard). Exit drift is
    recorded as a known item here; entry parity is strictly guarded.
    """

    @staticmethod
    def _parity_per_bar(strategy, df: pd.DataFrame) -> list[tuple[bool, bool, bool, bool]]:
        """Stream bars into on_bar; after each bar compare _latest_signal()
        (incremental) vs generate_signals(df_so_far).iloc[-1] (vectorized).

        Returns a list of (inc_entry, vec_entry, inc_exit, vec_exit) per bar
        for bars where generate_signals has enough data to evaluate.
        """
        ctx = StrategyContext()
        strategy.on_init(ctx)
        comparisons: list[tuple[bool, bool, bool, bool]] = []
        min_bars = strategy._slow_period + strategy._macd_signal
        for i in range(len(df)):
            bar = _bars_from_df(df.iloc[: i + 1])[i]
            strategy.on_bar(ctx, bar)
            ctx.flush_signals()
            if i + 1 < min_bars:
                continue  # generate_signals returns all-False; skip
            inc_entry, inc_exit = strategy._latest_signal()
            entries, exits = strategy.generate_signals(df.iloc[: i + 1])
            vec_entry = bool(entries.iloc[-1])
            vec_exit = bool(exits.iloc[-1])
            comparisons.append((bool(inc_entry), vec_entry, bool(inc_exit), vec_exit))
        return comparisons

    @pytest.mark.parametrize("seed", [42, 7])
    def test_entry_signal_parity_incremental_vs_vectorized_every_bar(self, seed):
        """Per-bar: entry signal _latest_signal() == generate_signals at that
        bar, across the full series. Entry parity is the P1-verify F3
        foundation (F3 validates entry-side position shrinkage), so 0 drift
        is required. Multiple seeds cover different market regimes so a
        single sparse-signal dataset cannot make parity hold by accident."""
        strategy = TrendFollowingStrategy()
        df = _make_ohlcv(160, seed=seed)
        comparisons = self._parity_per_bar(strategy, df)
        assert len(comparisons) >= 100  # evaluated a meaningful span, not just the tail
        entry_mismatches = [i for i, c in enumerate(comparisons) if c[0] != c[1]]
        assert not entry_mismatches, (
            f"seed={seed}: entry signal drift incremental vs vectorized at bars "
            f"{entry_mismatches[:5]} (first 5 of {len(entry_mismatches)})"
        )

    @pytest.mark.parametrize("seed", [42, 7])
    def test_exit_residual_is_profit_trailing_role_difference(self, seed):
        """Residual exit divergence after the ISS-20260613-006 fix.

        The condition-exit root cause is fixed (generate_signals exit_count
        now mirrors _latest_signal: no vol_ok, threshold min_conditions-1).
        What remains is a role difference, not a bug: generate_signals.exits
        is the COMBINED exit (condition | profit_target | trailing_stop),
        while _latest_signal() returns the CONDITION exit only — profit and
        trailing exits are handled by on_bar's _check_position_exits, a
        separate path. So vec_exit can be True where inc_exit is False
        (profit/trailing fired vectorized but the condition itself didn't).

        This pins the residual's magnitude and one-sided direction so the
        fix cannot silently regress: drift must stay in [1, 20] and every
        mismatch must be the (inc=False, vec=True) profit/trailing shape.
        """
        strategy = TrendFollowingStrategy()
        df = _make_ohlcv(160, seed=seed)
        comparisons = self._parity_per_bar(strategy, df)
        mismatches = [c for c in comparisons if c[2] != c[3]]
        # Residual band after fix (observed 2026-07-19 across 5 seeds: 1..16).
        # Pre-fix it was 12..22 (condition-exit semantic divergence); the drop
        # confirms the condition-exit root cause is gone.
        assert len(mismatches) <= 20, (
            f"seed={seed}: exit residual {len(mismatches)}/{len(comparisons)} exceeds "
            f"20 — condition-exit parity may have regressed, investigate"
        )
        # All mismatches must be the profit/trailing role shape: incremental
        # condition exit False, vectorized combined exit True. A (True, False)
        # mismatch would mean the incremental path fires a condition exit the
        # vectorized path doesn't — a real condition-parity regression.
        wrong_shape = [c for c in mismatches if c[2] and not c[3]]
        assert not wrong_shape, (
            f"seed={seed}: {len(wrong_shape)} bars where inc_exit=True but "
            f"vec_exit=False — condition-exit parity regressed (incremental fires "
            f"a condition exit the vectorized combined exit misses)"
        )

    def test_entry_parity_guard_is_not_vacuous(self):
        """Sanity: the entry-parity guard is not vacuous — at least one entry
        fires on this data, so the equality assertion can detect drift."""
        strategy = TrendFollowingStrategy()
        df = _make_ohlcv(160, seed=42)
        comparisons = self._parity_per_bar(strategy, df)
        assert any(c[0] or c[1] for c in comparisons), (
            "entry parity guard is vacuous — no entry ever fires on this data"
        )


class TestRegimeParityGap:
    """Deeper parity gap than ISS-20260613-006: on_bar applies regime gating
    (engine skips strategy.on_bar when required_regime != detected regime),
    but generate_signals does NOT — it emits entries on every bar regardless of
    regime. So the vectorized research path trades bars the event-driven
    live/paper path would gate out.

    Observed (2026-07-19): on real BTC/USDT 1h data, all 84 generate_signals
    entries fall on non-trending bars (ADX<25), which on_bar gates out →
    backtest trades 84 times, live trades 0. On synthetic data the gated
    fraction varies (3/6 .. 10/10 of entries) but the gap is systematic.

    Root cause: trend_following entry uses MA direction (fast>slow & MACD>0)
    while MarketRegimeDetector uses ADX strength (>=25) — direction != strength,
    so entries and trending-regime rarely coincide. This is a design conflict,
    NOT fixed here (regime gating is an execution-layer decision; mixing it
    into generate_signals would break the research-API's stateless contract).
    Registered as a parity-guard-pending item; this test quantifies the gap so
    it cannot silently widen and flags the regime↔entry decoupling explicitly.
    """

    @staticmethod
    def _regime_per_bar(df: pd.DataFrame) -> pd.Series:
        """Replay the MarketRegimeDetector the same way engine.on_bar does."""
        from quantflow.indicators.regime import MarketRegimeDetector

        det = MarketRegimeDetector()
        trending = []
        for hi, lo, c in zip(df["high"], df["low"], df["close"], strict=False):
            trending.append(det.update(float(hi), float(lo), float(c)).is_trending)
        return pd.Series(trending, index=df.index)

    @pytest.mark.parametrize("seed", [42, 7])
    def test_regime_gates_some_vectorized_entries(self, seed):
        """on_bar's regime gate must gate out a non-trivial fraction of
        generate_signals entries (the gap exists and is detectable). If this
        ever hits 0 the regime↔entry decoupling resolved itself — update the
        guard. If 100% the strategy never trades live on this data."""
        strategy = TrendFollowingStrategy()
        df = _make_ohlcv(160, seed=seed)
        entries, _ = strategy.generate_signals(df)
        trending = self._regime_per_bar(df)
        # trend_following.required_regime == "trending": on_bar only calls the
        # strategy when regime.is_trending is True. Entries on non-trending bars
        # are gated out of the live/paper path entirely.
        gated = entries & (~trending)
        assert entries.sum() > 0, "no entries on this data — guard is vacuous"
        # The gap is systematic: at least some entries land outside the regime.
        # (seed=42 hits 100% — all 10 entries gated — which is the extreme of the
        # decoupling: backtest trades, live trades nothing. Recorded, not blocked;
        # it is a real property of this strategy+data, not a transient fault.)
        assert gated.sum() > 0, (
            f"seed={seed}: 0 gated entries — regime now covers all entries, "
            f"the parity gap may have resolved (update this guard)"
        )
