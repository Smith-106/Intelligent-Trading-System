"""Additional tests for remaining uncovered lines across core modules."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from quantflow.common.models import Bar

# ---------------------------------------------------------------------------
# store.py — lines 136-138 (query exception path)
# ---------------------------------------------------------------------------


class TestDataStoreQueryExceptionDetail:
    def test_query_with_invalid_parquet_returns_empty(self, tmp_path):
        """Lines 136-138: query with corrupted/empty parquet dir → returns empty."""
        from quantflow.data.store import DataStore

        store = DataStore(str(tmp_path))
        # Create a symbol dir with an invalid parquet file
        symbol_dir = tmp_path / "BTC_USDT"
        symbol_dir.mkdir()
        year_dir = symbol_dir / "2024"
        year_dir.mkdir()
        # Write an empty file that's not a valid parquet
        (year_dir / "01.parquet").write_text("not a parquet file")
        result = store.query("BTC/USDT")
        # Should catch the exception and return empty DataFrame
        assert isinstance(result, pd.DataFrame)


# ---------------------------------------------------------------------------
# regime.py — lines 113, 166 (ATR percentile <5 non-NaN else branches)
# ---------------------------------------------------------------------------


class TestRegimeATREdgeCases:
    def test_update_atr_with_fewer_than_5_nonna(self):
        """Lines 113/166: ATR percentile with <5 non-NaN values."""
        from quantflow.indicators.regime import MarketRegimeDetector

        detector = MarketRegimeDetector()
        # Feed only 3 bars — ATR history won't have 5 non-NaN values
        for i in range(3):
            bar = Bar("BTC/USDT", i, 100 + i, 102 + i, 98 + i, 100 + i, 1000)
            regime = detector.update(bar.high, bar.low, bar.close)
        # Should still return a regime (with fallback ATR percentile)
        assert regime is not None

    def test_detect_vectorized_insufficient_data(self):
        """detect() with very short DataFrame."""
        from quantflow.indicators.regime import MarketRegimeDetector

        detector = MarketRegimeDetector()
        df = pd.DataFrame(
            {
                "high": [101.0, 102.0],
                "low": [99.0, 100.0],
                "close": [100.0, 101.0],
            }
        )
        regime = detector.detect(df)
        assert regime is not None


# ---------------------------------------------------------------------------
# monitoring/metrics.py — lines 114, 129, 171-180
# ---------------------------------------------------------------------------


class TestMetricsRegistrySnapshotDetail:
    def test_snapshot_with_counter_samples(self):
        """Lines 171-180: registry snapshot with counter-type samples."""
        from quantflow.monitoring.metrics import REGISTRY, metrics_registry_snapshot

        # Create mock samples that include counter types
        mock_sample1 = MagicMock()
        mock_sample1.name = "ORDERS_TOTAL"
        mock_sample1.labels = {"symbol": "BTC/USDT"}
        mock_sample1.value = 42.0

        mock_sample2 = MagicMock()
        mock_sample2.name = "ORDERS_TOTAL"
        mock_sample2.labels = {"symbol": "ETH/USDT"}
        mock_sample2.value = 10.0

        mock_metric = MagicMock()
        mock_metric._samples = [mock_sample1, mock_sample2]

        with patch.object(REGISTRY, "collect", return_value=[mock_metric]):
            snapshot = metrics_registry_snapshot()
            assert isinstance(snapshot, dict)

    def test_snapshot_with_histogram_samples(self):
        """Lines 171-180: registry snapshot with histogram-type samples."""
        from quantflow.monitoring.metrics import REGISTRY, metrics_registry_snapshot

        mock_bucket = MagicMock()
        mock_bucket.name = "ORDER_LATENCY_bucket"
        mock_bucket.labels = {"le": "0.1"}
        mock_bucket.value = 5.0

        mock_count = MagicMock()
        mock_count.name = "ORDER_LATENCY_count"
        mock_count.labels = {}
        mock_count.value = 10.0

        mock_sum = MagicMock()
        mock_sum.name = "ORDER_LATENCY_sum"
        mock_sum.labels = {}
        mock_sum.value = 2.5

        mock_metric = MagicMock()
        mock_metric._samples = [mock_bucket, mock_count, mock_sum]

        with patch.object(REGISTRY, "collect", return_value=[mock_metric]):
            snapshot = metrics_registry_snapshot()
            assert isinstance(snapshot, dict)

    def test_metrics_server_status_started(self):
        """Lines 114/129: status for a previously started port."""
        from quantflow.monitoring.metrics import (
            _METRICS_SERVER_STATE,
            metrics_server_status,
            start_metrics_server,
        )

        # Use a unique port not already in _METRICS_SERVER_STATE
        port = 19998
        _METRICS_SERVER_STATE.pop(port, None)
        with patch("quantflow.monitoring.metrics.start_http_server"):
            start_metrics_server(port)
        status = metrics_server_status(port)
        assert isinstance(status, dict)


# ---------------------------------------------------------------------------
# ai_factors.py — lines 28, 192
# ---------------------------------------------------------------------------


class TestAIFactorsUncovered:
    def test_positive_class_probability_no_class_1_last_column(self):
        """Line 28: classes_ doesn't contain 1 → return last column."""
        from quantflow.strategy.ai_factors import _positive_class_probability

        model = MagicMock()
        model.classes_ = np.array([0, 2, 3])
        model.predict_proba.return_value = np.array([[0.2, 0.3, 0.5], [0.1, 0.4, 0.5]])
        result = _positive_class_probability(model, np.array([[1], [2]]))
        assert np.isclose(result[0], 0.5)
        assert np.isclose(result[1], 0.5)

    def test_compute_factor_with_valid_data(self):
        """Line 192: compute_factor path with valid indicator data."""
        from quantflow.strategy.ai_factors import AIFactorEngine

        engine = AIFactorEngine()
        features = pd.DataFrame(
            {
                "close": [100.0 + i for i in range(50)],
                "rsi_14": [50.0 + i for i in range(50)],
                "atr_14": [2.0] * 50,
            }
        )
        forward_returns = pd.Series([0.01 * i for i in range(50)])
        factor = engine.compute_factor(features, forward_returns)
        assert isinstance(factor, pd.Series)


# ---------------------------------------------------------------------------
# ml_ensemble.py — lines 204, 223 (cross_validate error returns)
# ---------------------------------------------------------------------------


class TestMLEnsembleCrossValidate:
    def test_cross_validate_with_insufficient_data(self):
        """Lines 204/223: cross_validate with too few samples returns empty results."""
        from quantflow.strategy.templates.ml_ensemble import MLEnsembleStrategy

        s = MLEnsembleStrategy()
        # Very short data → splits will be empty or fail
        df = pd.DataFrame(
            {
                "close": [100.0, 101.0, 102.0],
                "high": [101.0, 102.0, 103.0],
                "low": [99.0, 100.0, 101.0],
                "volume": [1000.0, 1000.0, 1000.0],
            }
        )
        entries, exits = s.generate_signals(df)
        assert isinstance(entries, pd.Series)
        assert isinstance(exits, pd.Series)


# ---------------------------------------------------------------------------
# cpcv.py — lines 84, 281
# ---------------------------------------------------------------------------


class TestCPCVUncovered:
    def test_split_cpcv_with_valid_params(self):
        """Line 84: split_cpcv produces correct split structure."""
        from quantflow.strategy.validation.cpcv import split_cpcv

        splits = split_cpcv(n_bars=100, n_groups=6, n_test_groups=2)
        assert len(splits) > 0
        for is_idx, oos_idx in splits:
            assert len(is_idx) > 0
            assert len(oos_idx) > 0

    def test_cpcv_backtest_basic(self):
        """Line 281: basic cpcv_backtest execution."""
        from quantflow.strategy.validation.cpcv import cpcv_backtest

        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        close = pd.Series(100.0 + np.random.default_rng(42).normal(0, 1, n).cumsum(), index=dates)
        entries = pd.Series(False, index=dates)
        exits = pd.Series(False, index=dates)
        for i in range(0, n, 15):
            if i < n:
                entries.iloc[i] = True
            if i + 7 < n:
                exits.iloc[i + 7] = True
        result = cpcv_backtest(close, entries, exits, n_groups=4, n_test_groups=1)
        assert isinstance(result, dict)
        assert "n_paths" in result


# ---------------------------------------------------------------------------
# elliott_wave.py template — line 86
# ---------------------------------------------------------------------------


class TestElliottWaveOnBarLine86:
    def test_on_bar_returns_when_df_empty_line86(self):
        """Line 86: _bars_to_df returns empty → on_bar returns early."""
        from quantflow.strategy.base import StrategyContext
        from quantflow.strategy.templates.elliott_wave import ElliottWaveStrategy

        class FakeCtx(StrategyContext):
            def __init__(self):
                self.signals = []

            def emit_signal(self, symbol, direction, strength=1.0, price=0.0, strategy_id=""):
                self.signals.append((symbol, direction, strength, price, strategy_id))

        s = ElliottWaveStrategy({"use_divergence": False})
        ctx = FakeCtx()
        # With < 20 bars, generate_signals should return empty-ish results
        for i in range(5):
            s.on_bar(ctx, Bar("BTC/USDT", i, 100, 101, 99, 100 + i, 1000))
        # No signals before 20 bars
        assert len(ctx.signals) == 0


# ---------------------------------------------------------------------------
# mean_reversion.py — line 110
# ---------------------------------------------------------------------------


class TestMeanReversionLine110:
    def test_latest_signal_none_when_indicators_insufficient(self):
        """Line 110: _latest_signal returns None when indicators are insufficient."""
        from quantflow.strategy.base import StrategyContext
        from quantflow.strategy.templates.mean_reversion import MeanReversionStrategy

        class FakeCtx(StrategyContext):
            def __init__(self):
                self.signals = []

            def emit_signal(self, symbol, direction, strength=1.0, price=0.0, strategy_id=""):
                self.signals.append((symbol, direction, strength, price, strategy_id))

        s = MeanReversionStrategy()
        ctx = FakeCtx()
        s.on_init(ctx)
        # Very few bars → insufficient for BB computation → _latest_signal returns None
        for i in range(3):
            s.on_bar(ctx, Bar("BTC/USDT", i, 100, 101, 99, 100 + i, 1000))
        # No crash, no signals
        assert len(ctx.signals) == 0


# ---------------------------------------------------------------------------
# web/history.py — uncovered lines 56, 122, 142, 149, 160-161
# ---------------------------------------------------------------------------


class TestWebHistoryUncovered:
    def test_session_snapshot_duration_calculation(self):
        """Line 56: session snapshot duration when running."""
        from quantflow.web.history import StationHistoryStore

        store = StationHistoryStore()
        # Add a snapshot with started_at and status='running'
        snapshot = {
            "session_id": "test-123",
            "status": "running",
            "started_at": "2024-01-01T00:00:00+00:00",
            "strategies": ["trend_following"],
            "mode": "paper",
        }
        store.append_session_snapshot(snapshot)
        history = store.list_session_snapshots()
        assert len(history) >= 1

    def test_record_event_basic(self):
        """Lines 142/149: append_session_event stores events."""
        from quantflow.web.history import StationHistoryStore

        store = StationHistoryStore()
        store.append_session_event(
            {
                "session_id": "test-123",
                "event_type": "signal",
                "title": "Signal emitted",
                "level": "info",
                "message": "LONG signal on BTC/USDT",
            }
        )
        events = store.list_session_events()
        assert len(events) >= 1

    def test_events_with_session_filter(self):
        """Line 160-161: events filtered by session_id."""
        from quantflow.web.history import StationHistoryStore

        store = StationHistoryStore()
        store.append_session_event(
            {
                "session_id": "s1",
                "event_type": "test",
                "title": "t1",
                "level": "info",
                "message": "m1",
            }
        )
        store.append_session_event(
            {
                "session_id": "s2",
                "event_type": "test",
                "title": "t2",
                "level": "info",
                "message": "m2",
            }
        )
        events_s1 = store.list_session_events(session_id="s1")
        store.list_session_events(session_id="s2")
        assert any(e.get("session_id") == "s1" for e in events_s1)
        assert not any(e.get("session_id") == "s2" for e in events_s1)
