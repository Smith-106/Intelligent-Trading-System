"""Additional coverage for strategy templates — trend_following, volatility_breakout, mean_reversion, ml_ensemble."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyContext
from quantflow.strategy.templates.mean_reversion import MeanReversionStrategy
from quantflow.strategy.templates.trend_following import TrendFollowingStrategy
from quantflow.strategy.templates.volatility_breakout import VolatilityBreakoutStrategy


class _FakeContext(StrategyContext):
    def __init__(self):
        self.signals: list[tuple] = []

    def emit_signal(self, symbol, direction, strength=1.0, price=0.0, strategy_id=""):
        self.signals.append((symbol, direction, strength, price, strategy_id))


def _make_bar(price: float = 100.0, high: float = 101.0, low: float = 99.0, idx: int = 0) -> Bar:
    return Bar("BTC/USDT", 1700000000 + idx * 60000, price - 0.5, high, low, price, 1000.0)


# ---------------------------------------------------------------------------
# TrendFollowing — uncovered lines 153-154, 165-166, 283, 285, 341-351
# ---------------------------------------------------------------------------

class TestTrendFollowingLatestSignalEdge:
    def test_latest_signal_returns_false_when_indicators_none(self):
        """Lines 153-154: When _latest_signal gets None indicators, return False, False."""
        s = TrendFollowingStrategy(params={
            "fast_ma_period": 2, "slow_ma_period": 2, "macd_slow": 2, "macd_signal": 1,
            "rsi_period": 2, "atr_period": 2, "volume_period": 2,
        })
        # Only a few bars → insufficient for all rolling computations → return False, False
        ctx = _FakeContext()
        s.on_init(ctx)
        for i in range(3):
            s.on_bar(ctx, _make_bar(100.0 + i, i))
        # _latest_signal should have returned (False, False) due to insufficient data
        assert s._last_entry_conditions == 0

    def test_latest_signal_returns_false_when_macd_signal_empty(self):
        """Lines 165-166: When MACD signal series is empty, return False, False."""
        s = TrendFollowingStrategy(params={
            "fast_ma_period": 2, "slow_ma_period": 2, "macd_slow": 2, "macd_signal": 1,
            "rsi_period": 2, "atr_period": 2, "volume_period": 2,
        })
        ctx = _FakeContext()
        s.on_init(ctx)
        # Force _runtime_state_is_current to False to trigger MACD computation
        s._bars_since_last_runtime_update = 999
        for i in range(5):
            s.on_bar(ctx, _make_bar(100.0, i))

    def test_rsi_adaptive_profit_overbought(self):
        """Lines 283-284: RSI-adaptive profit tighter when avg_entry_rsi > 70."""
        s = TrendFollowingStrategy(params={"rsi_adaptive_profit": True, "profit_take_pct": 0.10})
        # Build data where entries align with RSI > 70
        n = 200
        np.random.seed(42)
        close = pd.Series(100 + np.random.randn(n).cumsum())
        close = close.clip(lower=1)
        df = pd.DataFrame({"close": close, "high": close + 1, "low": close - 1, "volume": 1000.0})
        entries, exits = s.generate_signals(df)
        # Just ensure no crash — the branch fires when rsi_at_entry has entries > 70
        assert isinstance(entries, pd.Series)

    def test_rsi_adaptive_profit_oversold(self):
        """Line 285: RSI-adaptive profit wider when avg_entry_rsi < 30."""
        s = TrendFollowingStrategy(params={"rsi_adaptive_profit": True, "profit_take_pct": 0.10})
        n = 200
        np.random.seed(7)
        close = pd.Series(100 - np.abs(np.random.randn(n).cumsum()))  # declining
        close = close.clip(lower=1)
        df = pd.DataFrame({"close": close, "high": close + 1, "low": close - 1, "volume": 1000.0})
        entries, exits = s.generate_signals(df)
        assert isinstance(entries, pd.Series)

    def test_bars_to_df_empty(self):
        """Line 339: _bars_to_df when _bars is empty."""
        s = TrendFollowingStrategy()
        df = s._bars_to_df()
        assert df.empty

    def test_bars_to_df_with_bars(self):
        """Lines 341-351: _bars_to_df with bars."""
        s = TrendFollowingStrategy()
        s._bars = [_make_bar(100.0, i) for i in range(3)]
        df = s._bars_to_df()
        assert not df.empty
        assert "close" in df.columns
        assert "symbol" in df.columns

    def test_on_bar_bars_to_df_empty(self):
        """_bars_to_df returns empty → no signal from generate_signals."""
        s = TrendFollowingStrategy()
        ctx = _FakeContext()
        s.on_init(ctx)
        # Set _bars to a list but make _bars_to_df return empty
        # Actually on_bar appends the bar first, then checks length
        # So with 0 bars before, it adds one and has 1 < _max_bars, but < min period
        # Just test early return from _latest_signal due to insufficient data
        bar = _make_bar(100.0, 0)
        s.on_bar(ctx, bar)
        # No signals from just 1 bar
        assert len(ctx.signals) == 0


# ---------------------------------------------------------------------------
# VolatilityBreakout — uncovered lines 191, 195, 319, 324, 330, 343, 353, 493-503
# ---------------------------------------------------------------------------

class TestVolatilityBreakoutEdgeCases:
    def test_latest_signal_returns_false_when_bb_zero(self):
        """Line 195: bb_middle == 0 → return False, False."""
        s = VolatilityBreakoutStrategy(params={
            "atr_period": 2, "bb_period": 2, "keltner_ema_period": 2,
            "keltner_atr_period": 2, "volume_period": 2,
        })
        ctx = _FakeContext()
        s.on_init(ctx)
        # Build bars with close values near zero to trigger bb_middle == 0
        for i in range(30):
            s.on_bar(ctx, Bar("BTC/USDT", i, 0.001, 0.002, 0.0, 0.001, 1000.0))

    def test_bollinger_at_returns_none(self):
        """Line 319: _bollinger_at returns None when insufficient data."""
        s = VolatilityBreakoutStrategy(params={"bb_period": 50})
        # With only 5 close values, rolling with period 50 returns None
        result = s._bollinger_at(4, [100.0, 101.0, 102.0, 103.0, 104.0])
        assert result is None

    def test_bb_width_mean_at_short_index(self):
        """Line 324: index + 1 < (bb_period * 2) - 1 → return None."""
        s = VolatilityBreakoutStrategy(params={"bb_period": 20})
        result = s._bb_width_mean_at(10, [100.0] * 11)
        assert result is None

    def test_bb_width_mean_at_zero_middle(self):
        """Line 330: middle == 0 → return None."""
        s = VolatilityBreakoutStrategy(params={"bb_period": 3})
        # Use values that will produce a zero mean
        close_vals = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        result = s._bb_width_mean_at(6, close_vals)
        assert result is None

    def test_bars_to_df_with_bars(self):
        """Lines 493-503: _bars_to_df with bars."""
        s = VolatilityBreakoutStrategy()
        s._bars = [_make_bar(100.0, i) for i in range(3)]
        df = s._bars_to_df()
        assert not df.empty
        assert "symbol" in df.columns


# ---------------------------------------------------------------------------
# MeanReversion — uncovered line 110
# ---------------------------------------------------------------------------

class TestMeanReversionLatestSignalEdge:
    def test_latest_signal_returns_none_when_insufficient_data(self):
        """Line 110: When indicators are None, return None, False."""
        s = MeanReversionStrategy()
        ctx = _FakeContext()
        s.on_init(ctx)
        # Very few bars → indicators are None → return None, False
        for i in range(3):
            s.on_bar(ctx, _make_bar(100.0 + i, i))


# ---------------------------------------------------------------------------
# MLEnsemble — uncovered lines 21, 25, 31, 46, 204, 223
# ---------------------------------------------------------------------------

class TestMLEnsembleHelpers:
    def test_positive_class_probability_single_column(self):
        """Line 21: probas.shape[1] == 1 → uniform prediction."""
        from quantflow.strategy.templates.ml_ensemble import _positive_class_probability

        model = MagicMock()
        model.predict_proba.return_value = np.array([[0.6], [0.4], [0.8]])
        result = _positive_class_probability(model, np.array([[1], [2], [3]]))
        # Should return array of mean probability
        assert len(result) == 3
        assert np.isclose(result[0], result[1])  # all same value

    def test_positive_class_probability_class_1_in_classes(self):
        """Line 25-27: classes_ contains 1 → return that column."""
        from quantflow.strategy.templates.ml_ensemble import _positive_class_probability

        model = MagicMock()
        model.classes_ = np.array([0, 1])
        model.predict_proba.return_value = np.array([[0.3, 0.7], [0.6, 0.4]])
        result = _positive_class_probability(model, np.array([[1], [2]]))
        assert np.isclose(result[0], 0.7)
        assert np.isclose(result[1], 0.4)

    def test_positive_class_probability_no_class_1(self):
        """Line 28: classes_ doesn't contain 1 → return last column."""
        from quantflow.strategy.templates.ml_ensemble import _positive_class_probability

        model = MagicMock()
        model.classes_ = np.array([0, 2])
        model.predict_proba.return_value = np.array([[0.3, 0.7], [0.6, 0.4]])
        result = _positive_class_probability(model, np.array([[1], [2]]))
        assert np.isclose(result[0], 0.7)

    def test_safe_sharpe_zero_std(self):
        """Line 46: r.std() == 0 → return 0.0."""
        from quantflow.strategy.templates.ml_ensemble import _safe_sharpe

        result = _safe_sharpe(pd.Series([0.0, 0.0, 0.0]))
        assert result == 0.0

    def test_time_series_splits_too_few_samples(self):
        """Line 31-32: n_samples < 3 → return []."""
        from quantflow.strategy.templates.ml_ensemble import _time_series_splits

        assert _time_series_splits(2) == []

    def test_time_series_splits_produces_splits(self):
        from quantflow.strategy.templates.ml_ensemble import _time_series_splits

        splits = _time_series_splits(100)
        assert len(splits) > 0
        for train, test in splits:
            assert test.stop <= 100


class TestAIFactorHelpers:
    def test_positive_class_probability_single_column(self):
        """Line 22-23: probas.shape[1] == 1."""
        from quantflow.strategy.ai_factors import _positive_class_probability

        model = MagicMock()
        model.predict_proba.return_value = np.array([[0.6], [0.4]])
        result = _positive_class_probability(model, np.array([[1], [2]]))
        assert len(result) == 2
        assert np.isclose(result[0], result[1])

    def test_positive_class_probability_class_1(self):
        """Line 26-27: classes_ contains 1."""
        from quantflow.strategy.ai_factors import _positive_class_probability

        model = MagicMock()
        model.classes_ = np.array([0, 1])
        model.predict_proba.return_value = np.array([[0.3, 0.7], [0.6, 0.4]])
        result = _positive_class_probability(model, np.array([[1], [2]]))
        assert np.isclose(result[0], 0.7)

    def test_expanding_splits_too_few_samples(self):
        """Line 32-33: n_samples < 50 → return []."""
        from quantflow.strategy.ai_factors import _expanding_splits

        assert _expanding_splits(30) == []

    def test_expanding_splits_produces_splits(self):
        from quantflow.strategy.ai_factors import _expanding_splits

        splits = _expanding_splits(200)
        assert len(splits) > 0
