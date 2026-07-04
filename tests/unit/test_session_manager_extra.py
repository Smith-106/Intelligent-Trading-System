"""Tests for web/session_manager.py — remaining uncovered lines (133, 139-143, 188-190, 253, 389, 399, 535, 542, 592-593)."""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from quantflow.common.event_bus import Event, EventBus
from quantflow.common.models import EVENT_FILL, EVENT_ORDER, EVENT_RISK, EVENT_SIGNAL
from quantflow.web.history import StationHistoryStore
from quantflow.web.session_manager import (
    SessionStartRequest,
    StationSessionManager,
    SessionRuntime,
    _format_duration,
    _jsonable,
    _safe_number,
    MIN_TELEMETRY_INTERVAL_SECONDS,
    MAX_TELEMETRY_POINTS,
)


class TestSessionManagerStartUnknownStrategy:
    @pytest.mark.asyncio
    async def test_start_unknown_strategy_raises(self):
        """Line 133: Unknown strategy name → ValueError."""
        store = StationHistoryStore()
        manager = StationSessionManager(history_store=store)
        with patch("quantflow.web.session_manager.get_strategy_factories", return_value={}):
            with pytest.raises(ValueError, match="Unknown strategy"):
                await manager.start(SessionStartRequest(mode="paper", strategies=["nonexistent_strategy"]))


class TestSessionManagerStartCapitalAdjustment:
    @pytest.mark.asyncio
    async def test_start_with_capital_adjustment(self):
        """Lines 139-143: portfolio cash/capital/peak_equity update."""
        store = StationHistoryStore()
        manager = StationSessionManager(history_store=store)

        mock_strategy = MagicMock()
        mock_strategy.name = "test_s"

        mock_session = MagicMock()
        mock_session.portfolio.cash = 90000.0
        mock_session.portfolio.update_cash = MagicMock()
        mock_session.portfolio._initial_capital = 90000.0
        mock_session.portfolio._peak_equity = 90000.0
        mock_session.start = AsyncMock()
        # run_data_loop must return a coroutine (async def)
        async def _run_data_loop(**kwargs):
            pass
        mock_session.run_data_loop = _run_data_loop

        # Patch snapshot to return serializable dict
        serializable_snapshot = {
            "session_id": "test-s1",
            "running": False,
            "last_error": None,
            "portfolio": {"equity": 100000, "cash": 100000, "market_value": 0, "drawdown": 0},
            "health": {"running": False, "open_positions": 0, "pending_orders": 0},
            "kill_switch": {"active": False, "reason": None},
            "positions": [],
            "open_orders": [],
            "dashboard": {"status_label": "Stopped", "status_tone": "muted"},
            "telemetry": {"labels": [], "equity": [], "cash": [], "market_value": [], "drawdown": [], "open_positions": [], "pending_orders": []},
            "started_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
            "request": {"mode": "paper", "symbol": "BTC/USDT", "timeframe": "1h", "strategies": ["trend_following"]},
        }

        with patch("quantflow.web.session_manager.load_config") as mock_load, \
             patch("quantflow.web.session_manager.get_strategy_factories") as mock_factories, \
             patch("quantflow.web.session_manager.TradingSession", return_value=mock_session), \
             patch("quantflow.web.session_manager._gateway_config_from_env", return_value={"sandbox": False}), \
             patch.object(manager, "_attach_event_observers"), \
             patch.object(manager, "_record_lifecycle_event"), \
             patch("quantflow.web.session_manager.asyncio.create_task") as mock_create_task, \
             patch.object(manager, "snapshot", new_callable=AsyncMock, return_value=serializable_snapshot):
            mock_config = MagicMock()
            mock_load.return_value = mock_config
            mock_factories.return_value = {"trend_following": lambda _: mock_strategy}
            mock_task = MagicMock()
            mock_task.done.return_value = True
            mock_create_task.return_value = mock_task

            # Request with capital 100000 → cash_delta = 100000 - 90000 = 10000
            await manager.start(SessionStartRequest(
                mode="paper",
                strategies=["trend_following"],
                capital=100000.0,
                config_path="quantflow/config/default.yaml",
            ))

            mock_session.portfolio.update_cash.assert_called_once()
            # Lines 140-143: hasattr checks should pass and set values
            assert mock_session.portfolio._initial_capital == 100000.0
            assert mock_session.portfolio._peak_equity == 100000.0
            manager._runtime = None


class TestCaptureTaskOutcome:
    def test_capture_task_exception(self):
        """Lines 188-190: _capture_task_outcome with exception."""
        store = StationHistoryStore()
        manager = StationSessionManager(history_store=store)

        runtime = MagicMock(spec=SessionRuntime)
        runtime.session_id = "test-session"
        runtime.last_error = None

        # Create a completed task with exception
        async def failing():
            raise RuntimeError("test error")

        loop = asyncio.new_event_loop()
        try:
            task = loop.create_task(failing())
            loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
        finally:
            loop.close()

        # _capture_task_outcome checks the result and records error
        with patch.object(manager, "_record_lifecycle_event") as mock_record:
            manager._capture_task_outcome(task, runtime)
            assert runtime.last_error == "test error"
            mock_record.assert_called_once()


class TestSessionHistoryWithActiveRuntime:
    @pytest.mark.asyncio
    async def test_session_history_with_active_runtime(self):
        """Line 253: session_history when runtime is active."""
        store = StationHistoryStore()
        manager = StationSessionManager(history_store=store)

        # Create a mock runtime with an active (not done) loop_task
        mock_runtime = MagicMock(spec=SessionRuntime)
        mock_runtime.session_id = "active-session"
        mock_runtime.loop_task = MagicMock()
        mock_runtime.loop_task.done.return_value = False
        manager._runtime = mock_runtime

        result = await manager.session_history()
        # Should use active session_id as live_session_id
        assert isinstance(result, dict)
        assert "items" in result
        manager._runtime = None


class TestAttachDetachEventBusNotEventBus:
    def test_attach_event_bus_not_eventbus(self):
        """Line 389: _attach_event_observers when event_bus is not EventBus."""
        store = StationHistoryStore()
        manager = StationSessionManager(history_store=store)

        runtime = MagicMock(spec=SessionRuntime)
        runtime.session = MagicMock()
        runtime.session._event_bus = "not_an_eventbus"  # not an EventBus instance
        runtime.event_handlers = []

        manager._attach_event_observers(runtime)
        # Should return early without subscribing
        assert len(runtime.event_handlers) == 0

    def test_detach_event_bus_not_eventbus(self):
        """Line 399: _detach_event_observers when event_bus is not EventBus."""
        store = StationHistoryStore()
        manager = StationSessionManager(history_store=store)

        runtime = MagicMock(spec=SessionRuntime)
        runtime.session = MagicMock()
        runtime.session._event_bus = "not_an_eventbus"
        runtime.event_handlers = [("signal", MagicMock())]

        manager._detach_event_observers(runtime)
        # Should return early, handlers not cleared
        assert len(runtime.event_handlers) == 1


class TestRecordTelemetryPointSameState:
    def test_telemetry_same_state_update(self):
        """Line 535: same-state telemetry point replaces last."""
        store = StationHistoryStore()
        manager = StationSessionManager(history_store=store)

        runtime = MagicMock(spec=SessionRuntime)
        runtime.telemetry_points = [
            {"timestamp": "2024-01-01T00:00:00+00:00", "running": True, "equity": 100000, "cash": 50000, "market_value": 50000, "drawdown": -0.01, "open_positions": 1, "pending_orders": 0},
        ]

        snapshot = {
            "running": True,
            "portfolio": {"equity": 100000, "cash": 50000, "market_value": 50000, "drawdown": -0.01},
            "health": {"open_positions": 1, "pending_orders": 0},
            "positions": [],
            "open_orders": [],
        }
        # Same state within MIN_TELEMETRY_INTERVAL_SECONDS → replaces last point
        captured_at = datetime(2024, 1, 1, 0, 0, 1, tzinfo=UTC)
        manager._record_telemetry_point(runtime, snapshot, captured_at)
        assert len(runtime.telemetry_points) == 1
        assert runtime.telemetry_points[0]["timestamp"] == "2024-01-01T00:00:01+00:00"

    def test_telemetry_trim_to_max(self):
        """Line 542: trim telemetry points to MAX_TELEMETRY_POINTS."""
        store = StationHistoryStore()
        manager = StationSessionManager(history_store=store)

        runtime = MagicMock(spec=SessionRuntime)
        # Fill with MAX_TELEMETRY_POINTS + 10 points with valid ISO timestamps
        base = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        runtime.telemetry_points = [
            {
                "timestamp": (base + __import__("datetime").timedelta(hours=i)).isoformat(),
                "running": True,
                "equity": 100000 + i,
                "cash": 50000,
                "market_value": 50000 + i,
                "drawdown": -0.01,
                "open_positions": 1,
                "pending_orders": 0,
            }
            for i in range(MAX_TELEMETRY_POINTS + 10)
        ]

        # Different state → appends, then trims
        snapshot = {
            "running": True,
            "portfolio": {"equity": 200000, "cash": 100000, "market_value": 100000, "drawdown": -0.02},
            "health": {"open_positions": 2, "pending_orders": 1},
            "positions": [],
            "open_orders": [],
        }
        captured_at = datetime(2024, 2, 1, 0, 0, 0, tzinfo=UTC)
        manager._record_telemetry_point(runtime, snapshot, captured_at)
        assert len(runtime.telemetry_points) <= MAX_TELEMETRY_POINTS


class TestDashboardPayloadDegradedAndKillSwitch:
    def test_dashboard_degraded_status(self):
        """Line 592-593: dashboard payload with last_error → degraded."""
        store = StationHistoryStore()
        manager = StationSessionManager(history_store=store)

        runtime = MagicMock(spec=SessionRuntime)
        runtime.request = MagicMock()
        runtime.request.mode = "paper"
        runtime.request.symbol = "BTC/USDT"
        runtime.request.timeframe = "1h"
        runtime.request.strategies = ["trend_following"]
        runtime.session_id = "s1"
        runtime.telemetry_points = []
        runtime.event_handlers = []
        runtime.last_error = "connection lost"
        runtime.started_at = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC).isoformat()

        snapshot = {
            "running": False,
            "last_error": "connection lost",
            "portfolio": {"equity": 100000, "cash": 50000, "market_value": 50000},
            "health": {"open_positions": 0, "pending_orders": 0},
            "kill_switch": {"active": False, "reason": None},
            "positions": [],
            "open_orders": [],
        }
        events = []

        result = manager._dashboard_payload(runtime, snapshot, events)
        assert result["status_label"] == "Degraded"
        assert result["status_tone"] == "warning"

    def test_dashboard_kill_switch_status(self):
        """Line 589-590: dashboard payload with kill_switch active."""
        store = StationHistoryStore()
        manager = StationSessionManager(history_store=store)

        runtime = MagicMock(spec=SessionRuntime)
        runtime.request = MagicMock()
        runtime.request.mode = "paper"
        runtime.request.symbol = "BTC/USDT"
        runtime.request.timeframe = "1h"
        runtime.request.strategies = ["trend_following"]
        runtime.session_id = "s1"
        runtime.telemetry_points = []
        runtime.event_handlers = []
        runtime.last_error = None
        runtime.started_at = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC).isoformat()

        snapshot = {
            "running": False,
            "last_error": None,
            "portfolio": {"equity": 100000, "cash": 50000, "market_value": 50000},
            "health": {"open_positions": 0, "pending_orders": 0},
            "kill_switch": {"active": True, "reason": "max drawdown exceeded"},
            "positions": [],
            "open_orders": [],
        }
        events = []

        result = manager._dashboard_payload(runtime, snapshot, events)
        assert result["status_label"] == "Kill Switch"
        assert result["status_tone"] == "danger"
