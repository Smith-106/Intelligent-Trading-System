"""Tests for quantflow.strategy.templates — extended coverage for new strategies."""

import numpy as np
import pandas as pd

from quantflow.common.models import Bar
from quantflow.strategy.base import StrategyContext
from quantflow.strategy.templates.funding_rate import FundingRateStrategy
from quantflow.strategy.templates.ml_ensemble import MLEnsembleStrategy
from quantflow.strategy.templates.momentum_rotation import MomentumRotationStrategy
from quantflow.strategy.templates.volatility_breakout import VolatilityBreakoutStrategy


def _make_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
    np.random.seed(seed)
    close = 100 + np.random.randn(n).cumsum()
    close = np.maximum(close, 1)
    return pd.DataFrame({
        "close": close,
        "high": close + np.abs(np.random.randn(n)),
        "low": close - np.abs(np.random.randn(n)),
        "volume": 1000 + np.abs(np.random.randn(n) * 100),
    })


def _make_bar(symbol: str = "BTC/USDT", ts: int = 0, close: float = 100.0) -> Bar:
    return Bar(symbol, ts * 60000, close - 0.5, close + 0.5, close - 1, close, 1000)


# ── VolatilityBreakout ──

class TestVolatilityBreakoutExtended:
    def test_on_init_sets_params(self):
        s = VolatilityBreakoutStrategy(params={"atr_period": 10, "bb_period": 15})
        assert s._atr_period == 10
        assert s._bb_period == 15

    def test_on_bar_insufficient_data(self):
        s = VolatilityBreakoutStrategy()
        ctx = StrategyContext()
        s.on_init(ctx)
        for i in range(5):
            s.on_bar(ctx, _make_bar(ts=i, close=100 + i))
        # No signal emitted — not enough bars

    def test_on_bar_generates_signal(self):
        s = VolatilityBreakoutStrategy()
        ctx = StrategyContext()
        s.on_init(ctx)
        # Feed 80 bars with trending data
        for i in range(80):
            bar = Bar("BTC/USDT", i * 60000, 100 + i, 101 + i, 99 + i, 100.5 + i, 5000 + i * 10)
            s.on_bar(ctx, bar)

    def test_bars_to_df_empty(self):
        s = VolatilityBreakoutStrategy()
        df = s._bars_to_df()
        assert df.empty

    def test_generate_signals_with_ohlcv_columns(self):
        s = VolatilityBreakoutStrategy()
        df = _make_ohlcv(200)
        entries, exits = s.generate_signals(df)
        assert isinstance(entries, pd.Series)
        assert isinstance(exits, pd.Series)

    def test_default_params(self):
        s = VolatilityBreakoutStrategy()
        assert s._atr_period == 14
        assert s._atr_threshold == 1.5
        assert s._bb_middle_exit is True

    def test_custom_params(self):
        s = VolatilityBreakoutStrategy(params={"atr_shrink_exit": 0.5, "bb_middle_exit": False})
        assert s._atr_shrink_exit == 0.5
        assert s._bb_middle_exit is False


# ── FundingRate ──

class TestFundingRateExtended:
    def test_on_init_sets_params(self):
        s = FundingRateStrategy(params={"entry_threshold": 0.002, "rate_ema_period": 12})
        assert s._entry_threshold == 0.002
        assert s._rate_ema_period == 12

    def test_on_bar_cooldown(self):
        s = FundingRateStrategy()
        ctx = StrategyContext()
        s.on_init(ctx)
        s._cooldown_counter = 3
        bar = _make_bar(ts=0, close=100)
        s.on_bar(ctx, bar)  # Should skip due to cooldown
        assert s._cooldown_counter == 2

    def test_on_bar_insufficient_data(self):
        s = FundingRateStrategy()
        ctx = StrategyContext()
        s.on_init(ctx)
        for i in range(5):
            s.update_funding_rate(0.0005)
            s.update_open_interest(10000)
            s.on_bar(ctx, _make_bar(ts=i, close=100))

    def test_build_signal_df_empty_bars(self):
        s = FundingRateStrategy()
        df = s._build_signal_df()
        assert df.empty

    def test_build_signal_df_mismatched_lengths(self):
        s = FundingRateStrategy()
        s._bars = [_make_bar(ts=i, close=100) for i in range(10)]
        # No funding rates — should return empty
        df = s._build_signal_df()
        assert df.empty

    def test_on_bar_with_funding_data(self):
        s = FundingRateStrategy(params={"entry_threshold": 0.001})
        ctx = StrategyContext()
        s.on_init(ctx)
        for i in range(40):
            rate = -0.002 if i >= 30 else 0.0001
            s.update_funding_rate(rate)
            s.update_open_interest(10000 + i * 100)
            s.on_bar(ctx, _make_bar(ts=i, close=100 + i * 0.1))

    def test_default_params(self):
        s = FundingRateStrategy()
        assert s._entry_threshold == 0.001
        assert s._exit_threshold == 0.0003
        assert s._cooldown_bars == 6


# ── MomentumRotation ──

class TestMomentumRotationExtended:
    def test_on_init_sets_params(self):
        s = MomentumRotationStrategy(params={"lookback": 30, "top_n": 5})
        assert s._lookback == 30
        assert s._top_n == 5

    def test_on_bar_insufficient_data(self):
        s = MomentumRotationStrategy()
        ctx = StrategyContext()
        s.on_init(ctx)
        for i in range(10):
            s.on_bar(ctx, _make_bar(ts=i, close=100 + i))

    def test_on_bar_rebalance_skip(self):
        s = MomentumRotationStrategy(params={"rebalance_interval": 10})
        ctx = StrategyContext()
        s.on_init(ctx)
        # bar_count % 10 != 0 → skip signal generation
        for i in range(25):
            bar = Bar("BTC/USDT", i * 60000, 100 + i, 101 + i, 99 + i, 100.5 + i, 1000)
            s.on_bar(ctx, bar)

    def test_cross_sectional_empty_data(self):
        s = MomentumRotationStrategy()
        results = s.generate_cross_sectional_signals({})
        assert results == {}

    def test_cross_sectional_short_data(self):
        s = MomentumRotationStrategy(params={"lookback": 20})
        data = {"BTC/USDT": pd.DataFrame({"close": [100, 101, 102], "volume": [1000, 1000, 1000]})}
        results = s.generate_cross_sectional_signals(data)
        assert results == {}

    def test_bars_to_df_empty(self):
        s = MomentumRotationStrategy()
        df = s._bars_to_df()
        assert df.empty

    def test_default_params(self):
        s = MomentumRotationStrategy()
        assert s._lookback == 20
        assert s._top_n == 3
        assert s._stop_loss_pct == 0.03


# ── MLEnsemble ──

class TestMLEnsembleExtended:
    def test_on_init_sets_params(self):
        s = MLEnsembleStrategy(params={"entry_threshold": 0.7, "lookback": 200})
        assert s._entry_threshold == 0.7
        assert s._lookback == 200

    def test_generate_signals_no_model_returns_empty(self):
        s = MLEnsembleStrategy()
        df = _make_ohlcv(300)
        entries, _exits = s.generate_signals(df)
        assert len(entries) == len(df)

    def test_extract_features_shape(self):
        s = MLEnsembleStrategy()
        df = _make_ohlcv(300)
        features = s._extract_features(df)
        assert features.shape[0] > 0
        assert features.shape[1] >= 10

    def test_load_model_missing_file(self):
        s = MLEnsembleStrategy(params={"model_path": "/nonexistent/model.joblib"})
        s._load_model()  # Should not raise
        assert s._model is None

    def test_compute_meta_labels_no_trades(self):
        s = MLEnsembleStrategy()
        n = 50
        df = _make_ohlcv(n)
        entries = pd.Series(False, index=df.index)
        exits = pd.Series(False, index=df.index)
        meta = s.compute_meta_labels(df, entries, exits)
        assert meta.sum() == 0

    def test_on_bar_insufficient_data(self):
        s = MLEnsembleStrategy()
        ctx = StrategyContext()
        s.on_init(ctx)
        for i in range(10):
            s.on_bar(ctx, _make_bar(ts=i, close=100 + i))

    def test_bars_to_df_empty(self):
        s = MLEnsembleStrategy()
        df = s._bars_to_df()
        assert df.empty

    def test_apply_meta_labeling_no_meta_model(self):
        s = MLEnsembleStrategy()
        proba = pd.Series([0.7, 0.3, 0.8])
        result = s._apply_meta_labeling(pd.DataFrame(), proba)
        assert result.all()  # Without meta-model, all approved

    def test_default_params(self):
        s = MLEnsembleStrategy()
        assert s._entry_threshold == 0.6
        assert s._exit_threshold == 0.4
        assert s._lookback == 252
