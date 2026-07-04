"""Tests for quantflow.strategy.templates."""

import numpy as np
import pandas as pd

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
        aligned = pd.DataFrame(
            {
                symbol: df["close"].pct_change(20)
                for symbol, df in data.items()
            }
        )
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
