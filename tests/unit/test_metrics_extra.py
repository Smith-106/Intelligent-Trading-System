"""Tests for monitoring/metrics.py uncovered paths — server start, snapshot, portfolio update."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestMetricsServerStart:
    def test_start_metrics_server(self):
        """start_metrics_server starts a Prometheus HTTP server."""
        from quantflow.monitoring.metrics import start_metrics_server, metrics_server_status

        with patch("quantflow.monitoring.metrics.start_http_server") as mock_start:
            start_metrics_server(9092)
            mock_start.assert_called_once_with(9092)

    def test_metrics_server_status_unstarted(self):
        """metrics_server_status for an unstarted port."""
        from quantflow.monitoring.metrics import metrics_server_status

        status = metrics_server_status(9999)
        assert isinstance(status, dict)

    def test_metrics_registry_snapshot(self):
        """metrics_registry_snapshot returns a dict of metric samples."""
        from quantflow.monitoring.metrics import metrics_registry_snapshot

        with patch("quantflow.monitoring.metrics.REGISTRY") as mock_registry:
            mock_collector = MagicMock()
            mock_collector.__iter__ = lambda self: iter([])
            mock_registry.collect.return_value = []
            snapshot = metrics_registry_snapshot()
            assert isinstance(snapshot, dict)


class TestUpdatePortfolioMetrics:
    def test_update_portfolio_metrics(self):
        """update_portfolio_metrics sets gauge values."""
        from quantflow.monitoring.metrics import (
            update_portfolio_metrics,
            PORTFOLIO_VALUE,
            PORTFOLIO_CASH,
            PORTFOLIO_DRAWDOWN,
            POSITIONS_COUNT,
        )

        with patch.object(PORTFOLIO_VALUE, "set") as mock_value, \
             patch.object(PORTFOLIO_CASH, "set") as mock_cash, \
             patch.object(PORTFOLIO_DRAWDOWN, "set") as mock_dd, \
             patch.object(POSITIONS_COUNT, "set") as mock_pos:
            update_portfolio_metrics(100000.0, 50000.0, 0.05, 3)
            mock_value.assert_called_once_with(100000.0)
            mock_cash.assert_called_once_with(50000.0)
            mock_dd.assert_called_once_with(0.05)
            mock_pos.assert_called_once_with(3)


class TestMetricsSnapshotNonFinite:
    def test_snapshot_filters_non_finite(self):
        """Registry snapshot filters NaN/Inf values."""
        from quantflow.monitoring.metrics import metrics_registry_snapshot

        # Create a mock sample with NaN value
        mock_sample = MagicMock()
        mock_sample.name = "test_metric"
        mock_sample.labels = {}
        mock_sample.value = float("nan")

        mock_metric = MagicMock()
        mock_metric._samples = [mock_sample]

        with patch("quantflow.monitoring.metrics.REGISTRY") as mock_registry:
            mock_registry.collect.return_value = [mock_metric]
            snapshot = metrics_registry_snapshot()
            # NaN values should be filtered out
            assert "test_metric" not in snapshot or snapshot.get("test_metric") is None
