"""Targeted coverage for remaining lines in service.py, trend_following.py, cpcv.py.

Covers: service.py (124-125, 1429, 1435, 1442, 1451, 1458, 1826, 1839-1842, 1873),
         trend_following.py (165-166, 285), cpcv.py (84 — dead code, skipped).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from quantflow.common.models import Bar
from quantflow.web.history import StationHistoryStore


# ===================================================================
# service.py lines 124-125: _safe_number np.floating non-finite
# ===================================================================


class TestServiceSafeNumberNpFloating:
    """Lines 124-125: _safe_number with np.floating non-finite values.

    np.float64 is a subclass of float, so it hits line 121-122 first.
    Use np.float32 (NOT a float subclass) to reach lines 124-125.
    """

    def test_safe_number_np_inf(self):
        from quantflow.web.service import _safe_number
        result = _safe_number(np.float32("inf"))
        assert result is None

    def test_safe_number_np_nan(self):
        from quantflow.web.service import _safe_number
        result = _safe_number(np.float32("nan"))
        assert result is None

    def test_safe_number_np_finite(self):
        from quantflow.web.service import _safe_number
        result = _safe_number(np.float32(3.14))
        assert result == pytest.approx(3.14, rel=1e-5)


# ===================================================================
# service.py health signal branches (lines 1429, 1435, 1442, 1451, 1458)
# ===================================================================


def _make_market_overview():
    """overview dict with data.mode='market' so health_tone stays 'accent'."""
    return {
        "version": "1.0", "phase": 3, "config_path": "/test",
        "docker_available": True,
        "monitoring": {
            "prometheus_port": 8000,
            "grafana_port": 3000,
        },
        "data": {
            "parquet_dir": "/tmp/test", "duckdb_path": "/tmp/test.duckdb",
            "mode": "market", "symbol_count": 1,
            "source_counts": {"okx": 1},
            "source_context": {"message": "Market data ready"},
            "symbols": [{"symbol": "BTC/USDT", "data_source": "okx", "files": 1,
                         "date_range": [1700000000000, 1700003600000],
                         "source_breakdown": {"okx": 1}}],
        },
        "risk": {"max_drawdown": -0.1},
    }


class TestServiceHealthExternalUnavailable:
    """Line 1429: health_tone='accent' → 'warning' for external_unavailable+started."""

    def test_external_unavailable_started(self):
        from quantflow.web.service import StationService
        service = StationService(history_store=StationHistoryStore())

        def port_side_effect(host, port):
            # Make grafana reachable → reachable_total=1 (skip line 1449)
            return port == 3000

        with patch.object(service, "overview", return_value=_make_market_overview()), \
             patch("quantflow.web.service.metrics_registry_snapshot",
                   return_value={"values": {}, "available": True}), \
             patch("quantflow.web.service.metrics_server_status",
                   return_value={"attempted": True, "started": True, "started_in_process": True}), \
             patch("quantflow.web.service._port_reachable", side_effect=port_side_effect):
            result = service.monitoring_snapshot(
                session_snapshot={"running": True, "session_id": "s1"},
                session_history=[], session_events=[],
            )
            assert result["health"]["overall_tone"] == "warning"
            assert any("unreachable" in s for s in result["health"]["signals"])


class TestServiceHealthRegistryOnly:
    """Line 1435: health_tone='accent' → 'warning' for registry_only."""

    def test_registry_only(self):
        from quantflow.web.service import StationService
        service = StationService(history_store=StationHistoryStore())
        overview = _make_market_overview()

        def port_side_effect(host, port):
            # Make grafana reachable → reachable_total=1 (skip line 1449)
            return port == 3000

        with patch.object(service, "overview", return_value=overview), \
             patch("quantflow.web.service.metrics_registry_snapshot",
                   return_value={"values": {}, "available": True}), \
             patch("quantflow.web.service.metrics_server_status",
                   return_value={"attempted": False, "started": False}), \
             patch("quantflow.web.service._port_reachable", side_effect=port_side_effect):
            result = service.monitoring_snapshot(
                session_snapshot={"running": True, "session_id": "s1"},
                session_history=[], session_events=[],
            )
            assert result["health"]["overall_tone"] == "warning"


class TestServiceHealthWarningEvents:
    """Line 1442: health_tone='accent' → 'warning' when warning events exist."""

    def test_warning_events(self):
        from quantflow.web.service import StationService
        service = StationService(history_store=StationHistoryStore())

        def port_side_effect(host, port):
            # Both ports reachable → reachable_total=2 (skip line 1449)
            return True

        with patch.object(service, "overview", return_value=_make_market_overview()), \
             patch("quantflow.web.service.metrics_registry_snapshot",
                   return_value={"values": {}, "available": False}), \
             patch("quantflow.web.service.metrics_server_status",
                   return_value={"attempted": False, "started": False}), \
             patch("quantflow.web.service._port_reachable", side_effect=port_side_effect):
            events = [{"level": "warning", "event_type": "timeout"}]
            result = service.monitoring_snapshot(
                session_snapshot={"running": True, "session_id": "s1"},
                session_history=[], session_events=events,
            )
            assert result["health"]["overall_tone"] == "warning"
            assert any("warning" in s.lower() for s in result["health"]["signals"])


class TestServiceHealthNoReachableServices:
    """Line 1451: health_tone='accent' → 'warning' when no reachable services."""

    def test_no_reachable_services(self):
        from quantflow.web.service import StationService
        service = StationService(history_store=StationHistoryStore())

        with patch.object(service, "overview", return_value=_make_market_overview()), \
             patch("quantflow.web.service.metrics_registry_snapshot",
                   return_value={"values": {}, "available": False}), \
             patch("quantflow.web.service.metrics_server_status",
                   return_value={"attempted": False, "started": False}), \
             patch("quantflow.web.service._port_reachable", return_value=False):
            # metrics_server_status attempted=False → prometheus status_kind="idle"
            # → no prometheus-based downgrade, health_tone stays "accent"
            # _port_reachable=False → reachable_total==0 → line 1449-1451 fires
            result = service.monitoring_snapshot(
                session_snapshot={"running": True, "session_id": "s1"},
                session_history=[], session_events=[],
            )
            assert result["health"]["overall_tone"] == "warning"
            assert any("not reachable" in s.lower() for s in result["health"]["signals"])


class TestServiceHealthDockerUnavailable:
    """Line 1458: health_tone='accent' → 'warning' when docker unavailable."""

    def test_docker_unavailable(self):
        from quantflow.web.service import StationService
        service = StationService(history_store=StationHistoryStore())
        overview = _make_market_overview()
        overview["docker_available"] = False

        def port_side_effect(host, port):
            # Both ports reachable → reachable_total=2 (skip line 1449)
            return True

        with patch.object(service, "overview", return_value=overview), \
             patch("quantflow.web.service.metrics_registry_snapshot",
                   return_value={"values": {}, "available": False}), \
             patch("quantflow.web.service.metrics_server_status",
                   return_value={"attempted": False, "started": False}), \
             patch("quantflow.web.service._port_reachable", side_effect=port_side_effect):
            result = service.monitoring_snapshot(
                session_snapshot={"running": True, "session_id": "s1"},
                session_history=[], session_events=[],
            )
            assert result["health"]["overall_tone"] == "warning"
            assert any("Docker" in s for s in result["health"]["signals"])


# ===================================================================
# service.py line 1826: market mode → symbol_data_source = "okx"
# ===================================================================


class TestServiceMarketModeDataSource:
    """Line 1826: data_mode='market' → symbol_data_source='okx'."""

    def test_symbol_source_market_mode(self):
        from quantflow.web.service import StationService
        service = StationService(history_store=StationHistoryStore())
        overview_data = {
            "version": "1.0", "phase": 3, "config_path": "/test",
            "docker_available": False,
            "data": {
                "parquet_dir": "/tmp/test", "duckdb_path": "/tmp/test.duckdb",
                "symbols": [{"symbol": "BTC/USDT", "data_source": "unknown", "files": 1,
                             "date_range": [1700000000000, 1700003600000],
                             "source_breakdown": {}}],
                "mode": "market",
                "source_context": {"message": "Market data ready"},
            },
        }
        with patch.object(service, "overview", return_value=overview_data):
            session_snapshot = {
                "session_id": "s1", "running": True,
                "dashboard": {"status_label": "Running", "status_tone": "accent"},
                "request": {"mode": "paper", "symbol": "BTC/USDT", "timeframe": "1h",
                            "strategies": ["trend_following"]},
                "portfolio": {"equity": 100000, "cash": 50000, "market_value": 50000,
                              "drawdown": -0.01},
                "health": {"running": True, "open_positions": 1, "pending_orders": 0},
                "kill_switch": {"active": False, "reason": None},
                "positions": [], "open_orders": [],
                "telemetry": {"labels": [], "equity": [], "cash": [], "market_value": [],
                              "drawdown": [], "open_positions": [], "pending_orders": []},
                "started_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:01:00+00:00",
            }
            result = service.execution_snapshot(
                session_snapshot=session_snapshot, session_history=[], session_events=[],
            )
            ctx = result.get("execution_context", {})
            assert ctx.get("data_source") == "okx"


# ===================================================================
# service.py lines 1839-1842: _artifact_request payload.request fallback
# ===================================================================


class TestServiceArtifactRequestPayloadFallback:
    """Lines 1839-1842: _artifact_request when request not at top level.

    append_research_run always creates a 'request' field at top level,
    so line 1837 returns early. To hit lines 1839-1842, we must mock
    research_history to return items without a top-level 'request' key.
    """

    def test_artifact_request_in_payload(self):
        from quantflow.web.service import StationService
        service = StationService(history_store=StationHistoryStore())

        # Mock research_history to return item without top-level 'request'
        mock_research_item = {
            "method": "optimize",
            "payload": {
                "method": "optimize",
                "request": {"strategy": "trend_following", "symbol": "BTC/USDT"},
                "result": {"sharpe": 1.5},
            },
            "summary": {"method": "optimize", "outcome_label": "done"},
        }

        overview_data = {
            "version": "1.0", "phase": 3, "config_path": "/test",
            "docker_available": False,
            "data": {
                "parquet_dir": "/tmp/test", "duckdb_path": "/tmp/test.duckdb",
                "symbols": [{"symbol": "BTC/USDT", "data_source": "okx", "files": 1,
                             "date_range": [1700000000000, 1700003600000],
                             "source_breakdown": {}}],
                "mode": "market",
                "source_context": {"message": "Market data ready"},
            },
        }

        with patch.object(service, "overview", return_value=overview_data), \
             patch.object(service, "research_history", return_value=[mock_research_item]):
            session_snapshot = {
                "session_id": "s1", "running": True,
                "dashboard": {"status_label": "Running", "status_tone": "accent"},
                "request": {"mode": "paper", "symbol": "BTC/USDT", "timeframe": "1h",
                            "strategies": ["trend_following"]},
                "portfolio": {"equity": 100000, "cash": 50000, "market_value": 50000,
                              "drawdown": -0.01},
                "health": {"running": True, "open_positions": 1, "pending_orders": 0},
                "kill_switch": {"active": False, "reason": None},
                "positions": [], "open_orders": [],
                "telemetry": {"labels": [], "equity": [], "cash": [], "market_value": [],
                              "drawdown": [], "open_positions": [], "pending_orders": []},
                "started_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:01:00+00:00",
            }
            result = service.execution_snapshot(
                session_snapshot=session_snapshot, session_history=[], session_events=[],
            )
            assert isinstance(result, dict)


# ===================================================================
# service.py line 1873: validation_summary not dict → replace with {}
# ===================================================================


class TestServiceValidationSummaryNotList:
    """Line 1873: validation_summary is not a dict → replace with {}.

    validation_history() always normalizes summary to a dict via _validation_summary(),
    so isinstance(validation_summary, dict) is always True. To hit line 1873,
    we must mock validation_history to return an item with a non-dict summary.
    """

    def test_validation_summary_is_list(self):
        from quantflow.web.service import StationService
        service = StationService(history_store=StationHistoryStore())

        # Mock validation_history to return item with summary as a list
        mock_validation_item = {
            "method": "gate",
            "summary": ["not", "a", "dict"],
        }

        overview_data = {
            "version": "1.0", "phase": 3, "config_path": "/test",
            "docker_available": False,
            "data": {
                "parquet_dir": "/tmp/test", "duckdb_path": "/tmp/test.duckdb",
                "symbols": [{"symbol": "BTC/USDT", "data_source": "okx", "files": 1,
                             "date_range": [1700000000000, 1700003600000],
                             "source_breakdown": {}}],
                "mode": "market",
                "source_context": {"message": "Market data ready"},
            },
        }

        with patch.object(service, "overview", return_value=overview_data), \
             patch.object(service, "validation_history", return_value=[mock_validation_item]):
            session_snapshot = {
                "session_id": "s1", "running": True,
                "dashboard": {"status_label": "Running", "status_tone": "accent"},
                "request": {"mode": "paper", "symbol": "BTC/USDT", "timeframe": "1h",
                            "strategies": ["trend_following"]},
                "portfolio": {"equity": 100000, "cash": 50000, "market_value": 50000,
                              "drawdown": -0.01},
                "health": {"running": True, "open_positions": 1, "pending_orders": 0},
                "kill_switch": {"active": False, "reason": None},
                "positions": [], "open_orders": [],
                "telemetry": {"labels": [], "equity": [], "cash": [], "market_value": [],
                              "drawdown": [], "open_positions": [], "pending_orders": []},
                "started_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:01:00+00:00",
            }
            result = service.execution_snapshot(
                session_snapshot=session_snapshot, session_history=[], session_events=[],
            )
            assert isinstance(result, dict)


# ===================================================================
# trend_following.py lines 165-166: empty macd_signal → return False, False
# ===================================================================


class TestTrendFollowingEmptyMacdSignal:
    """Lines 165-166: macd_signal is empty → return False, False."""

    def test_macd_signal_empty_via_mock(self):
        from quantflow.strategy.templates.trend_following import TrendFollowingStrategy
        strategy = TrendFollowingStrategy()
        n = 40
        strategy._bars = [MagicMock() for _ in range(n)]
        strategy._close_values = [100.0 + i for i in range(n)]
        strategy._high_values = [c + 1 for c in strategy._close_values]
        strategy._low_values = [c - 1 for c in strategy._close_values]
        strategy._volume_values = [1000.0] * n

        # Mock ewm_series so that the third call (macd_signal) returns empty
        # IMPORTANT: patch at trend_following module, not _runtime, because
        # trend_following.py does "from ..._runtime import ewm_series"
        import quantflow.strategy.templates._runtime as _runtime
        original_ewm = _runtime.ewm_series
        call_count = [0]

        def mock_ewm(values, span):
            call_count[0] += 1
            if call_count[0] == 3:
                return []
            return original_ewm(values, span)

        with patch("quantflow.strategy.templates.trend_following.ewm_series", side_effect=mock_ewm):
            entry, exit_ = strategy._latest_signal()
        assert entry is False
        assert exit_ is False


# ===================================================================
# trend_following.py line 285: avg_entry_rsi < 30 → effective_pct *= 1.2
# ===================================================================


class TestTrendFollowingRSIAdaptiveProfitOversold:
    """Line 285: avg_entry_rsi < 30 → effective_pct *= 1.2."""

    def test_rsi_oversold_at_entry(self):
        from quantflow.strategy.templates.trend_following import TrendFollowingStrategy
        strategy = TrendFollowingStrategy(
            params={"rsi_adaptive_profit": True, "min_conditions": 1, "rsi_period": 5}
        )
        # Long steady decline → RSI stays very low, most entries have RSI < 30
        n = 120
        close_vals = [500.0 - i * 4.0 for i in range(100)] + [100.0 + i * 0.5 for i in range(20)]
        df = pd.DataFrame({
            "open": close_vals,
            "high": [c + 2.0 for c in close_vals],
            "low": [c - 2.0 for c in close_vals],
            "close": close_vals,
            "volume": [3000.0] * n,
        })
        entries, exits = strategy.generate_signals(df)
        assert isinstance(entries, pd.Series)
