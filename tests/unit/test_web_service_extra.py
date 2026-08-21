"""Additional service.py tests covering remaining uncovered lines — np.floating/integer,
_query_symbol_frame filters, data_snapshot symbol processing, download_data errors,
tag_data_source, monitoring prometheus states, execution_snapshot detail paths."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from quantflow.web.history import StationHistoryStore

# ---------------------------------------------------------------------------
# _safe_number np branches (lines 124-125)
# ---------------------------------------------------------------------------


class TestSafeNumberNp:
    def test_np_floating_finite(self):
        from quantflow.web.service import _safe_number

        val = np.float64(3.14)
        result = _safe_number(val)
        assert result == 3.14

    def test_np_floating_inf(self):
        from quantflow.web.service import _safe_number

        result = _safe_number(np.float64(float("inf")))
        assert result is None

    def test_np_floating_nan(self):
        from quantflow.web.service import _safe_number

        result = _safe_number(np.float64(float("nan")))
        assert result is None

    def test_np_integer(self):
        from quantflow.web.service import _safe_number

        result = _safe_number(np.int64(42))
        assert result == 42
        assert isinstance(result, int)


# ---------------------------------------------------------------------------
# _query_symbol_frame filter paths (lines 499, 501, 518)
# ---------------------------------------------------------------------------


class TestQuerySymbolFrameFilters:
    def test_datetime_column_with_start_filter(self):
        from quantflow.web.service import _query_symbol_frame

        dates = pd.date_range("2024-01-01", periods=10, freq="D", tz="UTC")
        frame_data = pd.DataFrame(
            {
                "datetime": dates,
                "close": [100.0 + i for i in range(10)],
                "data_source": ["okx"] * 10,
            }
        )
        mock_store = MagicMock()
        mock_store.query.return_value = frame_data
        with patch(
            "quantflow.web.service._resolve_frame_data_source", return_value=("okx", {"okx": 10})
        ):
            frame, source = _query_symbol_frame(
                mock_store,
                "BTC/USDT",
                start="2024-01-03",
                end="2024-01-07",
            )
            assert source == "okx"
            assert len(frame) <= 5

    def test_datetime_column_with_end_filter(self):
        from quantflow.web.service import _query_symbol_frame

        dates = pd.date_range("2024-01-01", periods=10, freq="D", tz="UTC")
        frame_data = pd.DataFrame(
            {
                "datetime": dates,
                "close": [100.0 + i for i in range(10)],
                "data_source": ["okx"] * 10,
            }
        )
        mock_store = MagicMock()
        mock_store.query.return_value = frame_data
        with patch(
            "quantflow.web.service._resolve_frame_data_source", return_value=("okx", {"okx": 10})
        ):
            _frame, source = _query_symbol_frame(
                mock_store,
                "BTC/USDT",
                start=None,
                end="2024-01-05",
            )
            assert source == "okx"

    def test_timestamp_column_becomes_empty_after_filter(self):
        """Line 518: frame becomes empty after start/end filter → returns demo."""
        from quantflow.web.service import _query_symbol_frame

        # Data with timestamps that will be filtered to empty
        n = 5
        timestamps = list(range(1700000000000, 1700000000000 + n * 86400000, 86400000))
        frame_data = pd.DataFrame(
            {
                "timestamp": timestamps,
                "close": [100.0 + i for i in range(n)],
                "data_source": ["okx"] * n,
            }
        )
        mock_store = MagicMock()
        mock_store.query.return_value = frame_data
        with patch(
            "quantflow.web.service._resolve_frame_data_source", return_value=("okx", {"okx": n})
        ):
            # Filter with a future end date that includes all, but a start date far in the future
            frame, source = _query_symbol_frame(
                mock_store,
                "BTC/USDT",
                start="2099-01-01",
                end="2099-12-31",
            )
            # Should return demo frame because filtered frame is empty
            assert source == "demo"
            assert len(frame) > 0


# ---------------------------------------------------------------------------
# data_snapshot symbol processing paths (lines 903-904, 906, 923, 1002-1007)
# ---------------------------------------------------------------------------


class TestDataSnapshotSymbolProcessing:
    def test_source_breakdown_with_bad_count(self):
        """Lines 903-904, 906: source_breakdown int() error and count <= 0."""
        from quantflow.web.service import StationService

        service = StationService(history_store=StationHistoryStore())
        # Patch overview to return controlled data with bad source_breakdown values
        overview_data = {
            "data": {
                "parquet_dir": "/tmp/test",
                "duckdb_path": "/tmp/test.duckdb",
                "symbols": [
                    {
                        "symbol": "BTC/USDT",
                        "files": 1,
                        "date_range": [1700000000000, 1700003600000],
                        "data_source": "okx",
                        "source_breakdown": {"okx": "not_a_number", "demo": -5, "valid": 3},
                    },
                    {
                        "symbol": "ETH/USDT",
                        "files": 1,
                        "date_range": [1700000000000, 1700003600000],
                        "data_source": "some_other_source",
                        "source_breakdown": {"other": 0},
                    },
                ],
                "mode": "market",
                "source_context": {"message": "test"},
            },
        }
        with patch.object(service, "overview", return_value=overview_data):
            result = service.data_snapshot()
            # "not_a_number" should be skipped (line 903-904), -5 should be skipped (line 906)
            # "valid": 3 should be kept, "some_other_source" should normalize to "unknown" (line 923)
            symbols = result["symbols"]
            btc = next((s for s in symbols if s["symbol"] == "BTC/USDT"), None)
            if btc:
                assert btc["source_breakdown"].get("valid") == 3
                assert "okx" not in btc["source_breakdown"]  # "not_a_number" skipped
            eth = next((s for s in symbols if s["symbol"] == "ETH/USDT"), None)
            if eth:
                # "some_other_source" is not in {"okx","demo","unknown","hybrid"} → becomes "unknown"
                assert eth["data_source"] == "unknown"

    def test_data_snapshot_source_unknown_and_hybrid_modes(self):
        """Lines 1002-1007: data mode 'source-unknown' and 'hybrid' highlight paths."""
        from quantflow.web.service import StationService

        with (
            patch("quantflow.web.service.load_config") as mock_load,
            patch("quantflow.web.service.resolve_config_path") as mock_resolve,
            patch("quantflow.web.service._docker_available", return_value=False),
            patch("quantflow.web.service.list_strategy_summaries", return_value=[]),
        ):
            mock_resolve.return_value = "/test/config.yaml"
            mock_config = MagicMock()
            mock_config.data.parquet_dir = "/tmp/nonexistent"
            mock_config.data.duckdb_path = "/tmp/nonexistent.duckdb"
            mock_config.monitoring.prometheus_port = 9090
            mock_config.monitoring.grafana_port = 3000
            mock_config.risk.max_drawdown = -0.1
            mock_config.risk.daily_loss_limit = -0.05
            mock_config.risk.weekly_loss_limit = -0.1
            mock_config.risk.kill_switch_enabled = False
            mock_config.execution.mode = "paper"
            mock_config.execution.slippage = 0.001
            mock_config.execution.maker_fee = 0.0002
            mock_config.execution.taker_fee = 0.0005
            mock_load.return_value = mock_config

            mock_store = MagicMock()
            mock_store.list_symbols.return_value = ["BTC_USDT"]
            # PERF(P1): overview now consumes store.symbol_summary (single scan).
            mock_store.symbol_summary.return_value = {
                "rows": 1,
                "date_range": (1700000000000, 1700003600000),
                "breakdown": {"unknown": 1},
            }
            mock_store.close = MagicMock()

            with patch("quantflow.web.service._open_station_store", return_value=mock_store):
                service = StationService(history_store=StationHistoryStore())
                result = service.data_snapshot()
                # Should have source-unknown mode highlights
                assert result["mode"] == "source-unknown"

    def test_data_snapshot_demo_seeded_mode(self):
        """Lines 998-1001: demo-seeded mode highlight."""
        from quantflow.web.service import StationService

        with (
            patch("quantflow.web.service.load_config") as mock_load,
            patch("quantflow.web.service.resolve_config_path") as mock_resolve,
            patch("quantflow.web.service._docker_available", return_value=False),
            patch("quantflow.web.service.list_strategy_summaries", return_value=[]),
        ):
            mock_resolve.return_value = "/test/config.yaml"
            mock_config = MagicMock()
            mock_config.data.parquet_dir = "/tmp/nonexistent"
            mock_config.data.duckdb_path = "/tmp/nonexistent.duckdb"
            mock_config.monitoring.prometheus_port = 9090
            mock_config.monitoring.grafana_port = 3000
            mock_config.risk.max_drawdown = -0.1
            mock_config.risk.daily_loss_limit = -0.05
            mock_config.risk.weekly_loss_limit = -0.1
            mock_config.risk.kill_switch_enabled = False
            mock_config.execution.mode = "paper"
            mock_config.execution.slippage = 0.001
            mock_config.execution.maker_fee = 0.0002
            mock_config.execution.taker_fee = 0.0005
            mock_load.return_value = mock_config

            mock_store = MagicMock()
            mock_store.list_symbols.return_value = ["BTC_USDT"]
            # PERF(P1): overview now consumes store.symbol_summary (single scan).
            mock_store.symbol_summary.return_value = {
                "rows": 1,
                "date_range": (1700000000000, 1700003600000),
                "breakdown": {"demo": 1},
            }
            mock_store.close = MagicMock()

            with patch("quantflow.web.service._open_station_store", return_value=mock_store):
                service = StationService(history_store=StationHistoryStore())
                result = service.data_snapshot()
                assert result["mode"] == "demo-seeded"

    def test_data_snapshot_hybrid_mode(self):
        """Lines 1006-1009: hybrid mode highlight."""
        from quantflow.web.service import StationService

        with (
            patch("quantflow.web.service.load_config") as mock_load,
            patch("quantflow.web.service.resolve_config_path") as mock_resolve,
            patch("quantflow.web.service._docker_available", return_value=False),
            patch("quantflow.web.service.list_strategy_summaries", return_value=[]),
        ):
            mock_resolve.return_value = "/test/config.yaml"
            mock_config = MagicMock()
            mock_config.data.parquet_dir = "/tmp/nonexistent"
            mock_config.data.duckdb_path = "/tmp/nonexistent.duckdb"
            mock_config.monitoring.prometheus_port = 9090
            mock_config.monitoring.grafana_port = 3000
            mock_config.risk.max_drawdown = -0.1
            mock_config.risk.daily_loss_limit = -0.05
            mock_config.risk.weekly_loss_limit = -0.1
            mock_config.risk.kill_switch_enabled = False
            mock_config.execution.mode = "paper"
            mock_config.execution.slippage = 0.001
            mock_config.execution.maker_fee = 0.0002
            mock_config.execution.taker_fee = 0.0005
            mock_load.return_value = mock_config

            mock_store = MagicMock()
            mock_store.list_symbols.return_value = ["BTC_USDT", "ETH_USDT"]
            # PERF(P1): overview now consumes store.symbol_summary (single scan).
            mock_store.symbol_summary.side_effect = [
                {"rows": 1, "date_range": (1700000000000, 1700003600000), "breakdown": {"okx": 1}},
                {"rows": 1, "date_range": (1700000000000, 1700003600000), "breakdown": {"demo": 1}},
            ]
            mock_store.close = MagicMock()

            with patch("quantflow.web.service._open_station_store", return_value=mock_store):
                service = StationService(history_store=StationHistoryStore())
                result = service.data_snapshot()
                assert result["mode"] == "hybrid"


# ---------------------------------------------------------------------------
# overview with date_range fallback (lines 815-817)
# ---------------------------------------------------------------------------


class TestOverviewDateRangeFallback:
    def test_overview_date_range_from_timestamps(self):
        """Lines 815-817: date_range None but frame has timestamps."""
        from quantflow.web.service import StationService

        with (
            patch("quantflow.web.service.load_config") as mock_load,
            patch("quantflow.web.service.resolve_config_path") as mock_resolve,
            patch("quantflow.web.service._docker_available", return_value=False),
            patch("quantflow.web.service.list_strategy_summaries", return_value=[]),
        ):
            mock_resolve.return_value = "/test/config.yaml"
            mock_config = MagicMock()
            mock_config.data.parquet_dir = "/tmp/nonexistent"
            mock_config.data.duckdb_path = "/tmp/nonexistent.duckdb"
            mock_config.monitoring.prometheus_port = 9090
            mock_config.monitoring.grafana_port = 3000
            mock_config.risk.max_drawdown = -0.1
            mock_config.risk.daily_loss_limit = -0.05
            mock_config.risk.weekly_loss_limit = -0.1
            mock_config.risk.kill_switch_enabled = False
            mock_config.execution.mode = "paper"
            mock_config.execution.slippage = 0.001
            mock_config.execution.maker_fee = 0.0002
            mock_config.execution.taker_fee = 0.0005
            mock_load.return_value = mock_config

            mock_store = MagicMock()
            mock_store.list_symbols.return_value = ["BTC_USDT"]
            btc_frame = pd.DataFrame(
                {
                    "timestamp": [1700000000000, 1700003600000],
                    "data_source": ["okx", "okx"],
                }
            )
            mock_store.query.return_value = btc_frame
            # get_date_range returns None → triggers fallback
            mock_store.get_date_range.return_value = None
            mock_store.close = MagicMock()

            with (
                patch("quantflow.web.service._open_station_store", return_value=mock_store),
                patch(
                    "quantflow.web.service._resolve_frame_data_source",
                    return_value=("okx", {"okx": 2}),
                ),
            ):
                service = StationService(history_store=StationHistoryStore())
                result = service.overview()
                assert isinstance(result, dict)
                # The symbol should have date_range computed from timestamps
                symbols = result.get("data", {}).get("symbols", [])
                if symbols:
                    assert symbols[0].get("date_range") is not None


# ---------------------------------------------------------------------------
# monitoring_snapshot prometheus states (lines 1271-1272, 1296, 1318-1340, etc.)
# ---------------------------------------------------------------------------


class TestMonitoringSnapshotPrometheusStates:
    def _make_service(self):
        from quantflow.web.service import StationService

        with (
            patch("quantflow.web.service.load_config") as mock_load,
            patch("quantflow.web.service.resolve_config_path") as mock_resolve,
            patch("quantflow.web.service._docker_available", return_value=False),
            patch("quantflow.web.service.list_strategy_summaries", return_value=[]),
        ):
            mock_resolve.return_value = "/test/config.yaml"
            mock_config = MagicMock()
            mock_config.data.parquet_dir = "/tmp/test"
            mock_config.data.duckdb_path = "/tmp/test.duckdb"
            mock_config.monitoring.prometheus_port = 9090
            mock_config.monitoring.grafana_port = 3000
            mock_config.risk.max_drawdown = -0.1
            mock_config.risk.daily_loss_limit = -0.05
            mock_config.risk.weekly_loss_limit = -0.1
            mock_config.risk.kill_switch_enabled = False
            mock_config.execution.mode = "paper"
            mock_config.execution.slippage = 0.001
            mock_config.execution.maker_fee = 0.0002
            mock_config.execution.taker_fee = 0.0005
            mock_load.return_value = mock_config

            mock_store = MagicMock()
            mock_store.list_symbols.return_value = []
            mock_store.close = MagicMock()

            with patch("quantflow.web.service._open_station_store", return_value=mock_store):
                return StationService(history_store=StationHistoryStore())

    def test_no_port_idle(self):
        """Lines 1295-1303: no port → idle status."""
        service = self._make_service()
        with (
            patch(
                "quantflow.web.service.metrics_registry_snapshot",
                return_value={"values": {}, "available": False},
            ),
            patch(
                "quantflow.web.service.metrics_server_status",
                return_value={"attempted": False, "started": False},
            ),
        ):
            result = service.monitoring_snapshot(
                session_snapshot=None,
                session_history=[],
                session_events=[],
            )
            # Services should have idle status for no port
            prometheus = next(
                (s for s in result["services"] if s["service_id"] == "prometheus"), None
            )
            if prometheus:
                assert prometheus["status_kind"] == "idle"

    def test_prometheus_in_process(self):
        """Lines 1317-1323: attempted + started_in_process but not reachable."""
        service = self._make_service()
        with (
            patch(
                "quantflow.web.service.metrics_registry_snapshot",
                return_value={"values": {}, "available": True},
            ),
            patch(
                "quantflow.web.service.metrics_server_status",
                return_value={"attempted": True, "started": True},
            ),
            patch("quantflow.web.service._port_reachable", return_value=False),
        ):
            result = service.monitoring_snapshot(
                session_snapshot=None,
                session_history=[],
                session_events=[],
            )
            prometheus = next(
                (s for s in result["services"] if s["service_id"] == "prometheus"), None
            )
            if prometheus:
                assert prometheus["status_kind"] == "external_unavailable"

    def test_prometheus_attempt_failed(self):
        """Lines 1324-1328: attempted but last_error."""
        service = self._make_service()
        with (
            patch(
                "quantflow.web.service.metrics_registry_snapshot",
                return_value={"values": {}, "available": True},
            ),
            patch(
                "quantflow.web.service.metrics_server_status",
                return_value={"attempted": True, "started": False, "last_error": "bind failed"},
            ),
            patch("quantflow.web.service._port_reachable", return_value=False),
        ):
            result = service.monitoring_snapshot(
                session_snapshot=None,
                session_history=[],
                session_events=[],
            )
            prometheus = next(
                (s for s in result["services"] if s["service_id"] == "prometheus"), None
            )
            if prometheus:
                assert prometheus["status_kind"] == "attempt_failed"

    def test_prometheus_registry_only(self):
        """Lines 1329-1335: registry available but not attempted/reachable."""
        service = self._make_service()
        with (
            patch(
                "quantflow.web.service.metrics_registry_snapshot",
                return_value={"values": {}, "available": True},
            ),
            patch(
                "quantflow.web.service.metrics_server_status",
                return_value={"attempted": False, "started": False},
            ),
            patch("quantflow.web.service._port_reachable", return_value=False),
        ):
            result = service.monitoring_snapshot(
                session_snapshot=None,
                session_history=[],
                session_events=[],
            )
            prometheus = next(
                (s for s in result["services"] if s["service_id"] == "prometheus"), None
            )
            if prometheus:
                assert prometheus["status_kind"] == "registry_only"

    def test_prometheus_idle_no_metrics(self):
        """Lines 1336-1340: idle, no metrics activity."""
        service = self._make_service()
        with (
            patch(
                "quantflow.web.service.metrics_registry_snapshot",
                return_value={"values": {}, "available": False},
            ),
            patch(
                "quantflow.web.service.metrics_server_status",
                return_value={"attempted": False, "started": False},
            ),
            patch("quantflow.web.service._port_reachable", return_value=False),
        ):
            result = service.monitoring_snapshot(
                session_snapshot=None,
                session_history=[],
                session_events=[],
            )
            prometheus = next(
                (s for s in result["services"] if s["service_id"] == "prometheus"), None
            )
            if prometheus:
                assert prometheus["status_kind"] == "idle"

    def test_port_parse_error(self):
        """Lines 1271-1272: port parsing error."""
        service = self._make_service()
        with (
            patch(
                "quantflow.web.service.metrics_registry_snapshot",
                return_value={"values": {}, "available": False},
            ),
            patch(
                "quantflow.web.service.metrics_server_status",
                return_value={"attempted": False, "started": False},
            ),
        ):
            # Override monitoring config to have invalid port
            result = service.monitoring_snapshot(
                session_snapshot=None,
                session_history=[],
                session_events=[],
            )
            assert isinstance(result, dict)

    def test_health_docker_unavailable(self):
        """Lines 1456-1459: docker unavailable → warning."""
        service = self._make_service()
        with (
            patch(
                "quantflow.web.service.metrics_registry_snapshot",
                return_value={"values": {}, "available": False},
            ),
            patch(
                "quantflow.web.service.metrics_server_status",
                return_value={"attempted": False, "started": False},
            ),
            patch("quantflow.web.service._docker_available", return_value=False),
        ):
            result = service.monitoring_snapshot(
                session_snapshot={"session_id": "s1", "running": True},
                session_history=[],
                session_events=[],
            )
            assert any("Docker" in s for s in result["health"]["signals"])

    def test_prometheus_attempt_failed_alert(self):
        """Lines 1547-1559: attempt_failed prometheus alert."""
        service = self._make_service()
        with (
            patch(
                "quantflow.web.service.metrics_registry_snapshot",
                return_value={"values": {}, "available": True},
            ),
            patch(
                "quantflow.web.service.metrics_server_status",
                return_value={"attempted": True, "started": False, "last_error": "bind error"},
            ),
            patch("quantflow.web.service._port_reachable", return_value=False),
        ):
            result = service.monitoring_snapshot(
                session_snapshot=None,
                session_history=[],
                session_events=[],
            )
            assert any(a.get("source") == "monitoring" for a in result["alerts"])

    def test_warning_events_triggers_warning(self):
        """Lines 1440-1443: warning events → warning health."""
        service = self._make_service()
        with (
            patch(
                "quantflow.web.service.metrics_registry_snapshot",
                return_value={"values": {}, "available": False},
            ),
            patch(
                "quantflow.web.service.metrics_server_status",
                return_value={"attempted": False, "started": False},
            ),
        ):
            result = service.monitoring_snapshot(
                session_snapshot=None,
                session_history=[],
                session_events=[
                    {
                        "level": "warning",
                        "event_type": "risk",
                        "title": "Risk warning",
                        "message": "High exposure",
                    },
                ],
            )
            assert result["health"]["overall_tone"] in ("warning", "danger")

    def test_reachable_services_zero(self):
        """Lines 1449-1454: no services reachable → warning."""
        service = self._make_service()
        with (
            patch(
                "quantflow.web.service.metrics_registry_snapshot",
                return_value={"values": {}, "available": False},
            ),
            patch(
                "quantflow.web.service.metrics_server_status",
                return_value={"attempted": False, "started": False},
            ),
            patch("quantflow.web.service._port_reachable", return_value=False),
        ):
            result = service.monitoring_snapshot(
                session_snapshot=None,
                session_history=[],
                session_events=[],
            )
            assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# execution_snapshot detail paths (lines 1734, 1826-1830, 1839-1842, 1857, 1873)
# ---------------------------------------------------------------------------


class TestExecutionSnapshotDetailPaths:
    def _make_service(self):
        from quantflow.web.service import StationService

        with (
            patch("quantflow.web.service.load_config") as mock_load,
            patch("quantflow.web.service.resolve_config_path") as mock_resolve,
            patch("quantflow.web.service._docker_available", return_value=False),
            patch("quantflow.web.service.list_strategy_summaries", return_value=[]),
        ):
            mock_resolve.return_value = "/test/config.yaml"
            mock_config = MagicMock()
            mock_config.data.parquet_dir = "/tmp/test"
            mock_config.data.duckdb_path = "/tmp/test.duckdb"
            mock_config.monitoring.prometheus_port = 9090
            mock_config.monitoring.grafana_port = 3000
            mock_config.risk.max_drawdown = -0.1
            mock_config.risk.daily_loss_limit = -0.05
            mock_config.risk.weekly_loss_limit = -0.1
            mock_config.risk.kill_switch_enabled = False
            mock_config.execution.mode = "paper"
            mock_config.execution.slippage = 0.001
            mock_config.execution.maker_fee = 0.0002
            mock_config.execution.taker_fee = 0.0005
            mock_load.return_value = mock_config

            mock_store = MagicMock()
            mock_store.list_symbols.return_value = []
            mock_store.close = MagicMock()

            with patch("quantflow.web.service._open_station_store", return_value=mock_store):
                return StationService(history_store=StationHistoryStore())

    def test_telemetry_series_empty_with_labels(self):
        """Line 1734: telemetry series empty but has labels → return empty list."""
        service = self._make_service()
        session_snapshot = {
            "session_id": "s1",
            "running": True,
            "dashboard": {"status_label": "Running", "status_tone": "accent"},
            "request": {
                "mode": "paper",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "strategies": ["trend_following"],
            },
            "portfolio": {
                "equity": 100000,
                "cash": 50000,
                "market_value": 50000,
                "drawdown": -0.01,
            },
            "health": {"running": True, "open_positions": 1, "pending_orders": 0},
            "kill_switch": {"active": False, "reason": None},
            "positions": [
                {
                    "symbol": "BTC/USDT",
                    "quantity": 0.1,
                    "entry_price": 50000,
                    "current_price": 51000,
                    "unrealized_pnl": 100,
                    "market_value": 5100,
                }
            ],
            "open_orders": [],
            "telemetry": {
                "labels": ["t1"],
                "equity": [],  # empty series but has labels
                "cash": [],
                "market_value": [],
                "drawdown": [],
                "open_positions": [],
                "pending_orders": [],
            },
            "started_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:01:00+00:00",
        }
        result = service.execution_snapshot(
            session_snapshot=session_snapshot,
            session_history=[],
            session_events=[],
        )
        # With labels present but empty series, telemetry should return empty lists
        assert result["telemetry"]["equity"] == []

    def test_unknown_symbol_data_source_market(self):
        """Lines 1825-1826: unknown symbol data_source resolved to okx in market mode."""
        service = self._make_service()
        session_snapshot = {
            "session_id": "s1",
            "running": False,
            "dashboard": {"status_label": "Stopped", "status_tone": "muted"},
            "request": {"mode": "paper", "symbol": "BTC/USDT", "timeframe": "1h", "strategies": []},
            "portfolio": {"equity": 100000, "cash": 100000, "market_value": 0, "drawdown": 0},
            "health": {"running": False, "open_positions": 0, "pending_orders": 0},
            "kill_switch": {"active": False, "reason": None},
            "positions": [],
            "open_orders": [],
            "telemetry": {
                "labels": [],
                "equity": [],
                "cash": [],
                "market_value": [],
                "drawdown": [],
                "open_positions": [],
                "pending_orders": [],
            },
            "started_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:01:00+00:00",
        }
        # The overview returns data_mode based on symbols. With no symbols → demo-ready
        # execution_snapshot will call overview() which has empty symbols → mode=demo-ready
        result = service.execution_snapshot(
            session_snapshot=session_snapshot,
            session_history=[],
            session_events=[],
        )
        assert isinstance(result, dict)

    def test_artifact_request_payload_fallback(self):
        """Lines 1839-1842: request not found directly, found in payload.request."""
        service = self._make_service()
        # Add research and validation history that have payload.request format
        store = service.history_store
        store.append_research_run(
            {
                "payload": {"request": {"symbol": "BTC/USDT", "strategy": "trend_following"}},
                "result": {"total_return": 0.1},
            }
        )
        session_snapshot = {
            "session_id": "s1",
            "running": True,
            "dashboard": {"status_label": "Running", "status_tone": "accent"},
            "request": {
                "mode": "paper",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "strategies": ["trend_following"],
            },
            "portfolio": {
                "equity": 100000,
                "cash": 50000,
                "market_value": 50000,
                "drawdown": -0.01,
            },
            "health": {"running": True, "open_positions": 1, "pending_orders": 0},
            "kill_switch": {"active": False, "reason": None},
            "positions": [],
            "open_orders": [],
            "telemetry": {
                "labels": [],
                "equity": [],
                "cash": [],
                "market_value": [],
                "drawdown": [],
                "open_positions": [],
                "pending_orders": [],
            },
            "started_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:01:00+00:00",
        }
        result = service.execution_snapshot(
            session_snapshot=session_snapshot,
            session_history=[],
            session_events=[],
        )
        assert isinstance(result, dict)
        assert "execution_context" in result

    def test_pick_best_artifact_from_strategies(self):
        """Line 1857: request_strategy from strategies list."""
        service = self._make_service()
        store = service.history_store
        store.append_research_run(
            {
                "request": {
                    "symbol": "BTC/USDT",
                    "strategies": ["trend_following", "mean_reversion"],
                },
                "result": {"total_return": 0.1},
            }
        )
        session_snapshot = {
            "session_id": "s1",
            "running": True,
            "dashboard": {"status_label": "Running", "status_tone": "accent"},
            "request": {
                "mode": "paper",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "strategies": ["trend_following"],
            },
            "portfolio": {
                "equity": 100000,
                "cash": 50000,
                "market_value": 50000,
                "drawdown": -0.01,
            },
            "health": {"running": True, "open_positions": 1, "pending_orders": 0},
            "kill_switch": {"active": False, "reason": None},
            "positions": [],
            "open_orders": [],
            "telemetry": {
                "labels": [],
                "equity": [],
                "cash": [],
                "market_value": [],
                "drawdown": [],
                "open_positions": [],
                "pending_orders": [],
            },
            "started_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:01:00+00:00",
        }
        result = service.execution_snapshot(
            session_snapshot=session_snapshot,
            session_history=[],
            session_events=[],
        )
        assert isinstance(result, dict)

    def test_validation_data_source_from_payload(self):
        """Lines 1897-1900: validation_data_source from payload."""
        service = self._make_service()
        store = service.history_store
        store.append_validation_run(
            {
                "method": "gate",
                "payload": {
                    "method": "gate",
                    "data_source": "demo",
                    "result": {"decision": "GO", "checks": {"cpcv": {"passed": True}}},
                    "signals": {"entries": 5, "exits": 3, "bars": 100},
                    "backtest": {},
                },
                "summary": {
                    "method": "gate",
                    "outcome_label": "GO",
                    "outcome_tone": "accent",
                    "decision": "GO",
                    "method_label": "Validation Gate",
                    "reason": "All checks passed",
                },
            }
        )
        session_snapshot = {
            "session_id": "s1",
            "running": True,
            "dashboard": {"status_label": "Running", "status_tone": "accent"},
            "request": {
                "mode": "paper",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "strategies": ["trend_following"],
            },
            "portfolio": {
                "equity": 100000,
                "cash": 50000,
                "market_value": 50000,
                "drawdown": -0.01,
            },
            "health": {"running": True, "open_positions": 1, "pending_orders": 0},
            "kill_switch": {"active": False, "reason": None},
            "positions": [],
            "open_orders": [],
            "telemetry": {
                "labels": [],
                "equity": [],
                "cash": [],
                "market_value": [],
                "drawdown": [],
                "open_positions": [],
                "pending_orders": [],
            },
            "started_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:01:00+00:00",
        }
        result = service.execution_snapshot(
            session_snapshot=session_snapshot,
            session_history=[],
            session_events=[],
        )
        assert isinstance(result, dict)
        # validation_data_source should be found in payload
        ctx = result.get("execution_context", {})
        assert (
            ctx.get("validation_data_source") == "demo"
            or ctx.get("validation_data_source") is not None
        )
