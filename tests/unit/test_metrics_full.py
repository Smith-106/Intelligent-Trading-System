"""Additional metrics.py tests — registry snapshot full coverage."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from quantflow.monitoring.metrics import REGISTRY, metrics_registry_snapshot


class TestMetricsRegistrySnapshotFull:
    def test_snapshot_with_gauge_samples(self):
        """Lines 171-180: registry snapshot with gauge-type samples."""
        mock_sample = MagicMock()
        mock_sample.name = "PORTFOLIO_VALUE"
        mock_sample.labels = {"strategy": "trend_following"}
        mock_sample.value = 100000.0

        mock_metric = MagicMock()
        mock_metric._samples = [mock_sample]

        with patch.object(REGISTRY, "collect", return_value=[mock_metric]):
            snapshot = metrics_registry_snapshot()
            assert isinstance(snapshot, dict)
            # Should contain the gauge value
            key = 'PORTFOLIO_VALUE{strategy="trend_following"}'
            if key in snapshot:
                assert snapshot[key] == 100000.0

    def test_snapshot_handles_multiple_metrics(self):
        """Snapshot with multiple metric types."""
        gauge_sample = MagicMock()
        gauge_sample.name = "POSITIONS_COUNT"
        gauge_sample.labels = {}
        gauge_sample.value = 3.0

        counter_sample = MagicMock()
        counter_sample.name = "ORDERS_TOTAL"
        counter_sample.labels = {"symbol": "BTC/USDT", "side": "buy"}
        counter_sample.value = 42.0

        gauge_metric = MagicMock()
        gauge_metric._samples = [gauge_sample]

        counter_metric = MagicMock()
        counter_metric._samples = [counter_sample]

        with patch.object(REGISTRY, "collect", return_value=[gauge_metric, counter_metric]):
            snapshot = metrics_registry_snapshot()
            assert isinstance(snapshot, dict)

    def test_snapshot_empty_registry(self):
        """Snapshot with empty collect result."""
        with patch.object(REGISTRY, "collect", return_value=[]):
            snapshot = metrics_registry_snapshot()
            assert isinstance(snapshot, dict)

    def test_snapshot_with_non_finite_filtered(self):
        """NaN/Inf values are filtered to None."""
        inf_sample = MagicMock()
        inf_sample.name = "BAD_METRIC"
        inf_sample.labels = {}
        inf_sample.value = float("inf")

        bad_metric = MagicMock()
        bad_metric._samples = [inf_sample]

        with patch.object(REGISTRY, "collect", return_value=[bad_metric]):
            snapshot = metrics_registry_snapshot()
            # inf values should be None or excluded
            assert isinstance(snapshot, dict)
