"""Tests for web/session_manager.py — uncovered lifecycle, telemetry, and event description paths."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from quantflow.common.models import EVENT_FILL, EVENT_ORDER, EVENT_RISK, EVENT_SIGNAL
from quantflow.web.history import StationHistoryStore
from quantflow.web.session_manager import (
    SessionStartRequest,
    StationSessionManager,
    _format_duration,
    _jsonable,
    _safe_number,
)


class TestSafeNumber:
    def test_bool(self):
        assert _safe_number(True) is True
        assert _safe_number(False) is False

    def test_int(self):
        assert _safe_number(42) == 42

    def test_float_finite(self):
        assert _safe_number(3.14) == 3.14

    def test_float_nan(self):
        assert _safe_number(float("nan")) is None

    def test_float_inf(self):
        assert _safe_number(float("inf")) is None
        assert _safe_number(float("-inf")) is None

    def test_other(self):
        assert _safe_number("hello") == "hello"


class TestJsonable:
    def test_dict(self):
        result = _jsonable({"key": 1.0})
        assert result == {"key": 1.0}

    def test_list(self):
        result = _jsonable([1, 2])
        assert result == [1, 2]

    def test_tuple(self):
        result = _jsonable((1, 2))
        assert result == [1, 2]

    def test_set(self):
        result = _jsonable({1, 2})
        # Set → list, order may vary
        assert isinstance(result, list)
        assert len(result) == 2

    def test_path(self):
        from pathlib import Path

        result = _jsonable(Path("/tmp"))
        assert isinstance(result, str)

    def test_nan_becomes_none(self):
        result = _jsonable({"x": float("nan")})
        assert result["x"] is None


class TestFormatDuration:
    def test_seconds(self):
        assert _format_duration(30) == "30s"

    def test_minutes(self):
        assert _format_duration(90) == "1m 30s"

    def test_hours(self):
        assert _format_duration(3661) == "1h 01m"

    def test_zero(self):
        assert _format_duration(0) == "0s"

    def test_negative_clamps_to_zero(self):
        assert _format_duration(-5) == "0s"


class TestSessionManagerStop:
    @pytest.mark.asyncio
    async def test_stop_no_runtime(self):
        store = StationHistoryStore()
        manager = StationSessionManager(history_store=store)
        result = await manager.stop()
        assert result["running"] is False
        assert result["session_id"] is None


class TestSessionManagerCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_delegates_to_stop(self):
        store = StationHistoryStore()
        manager = StationSessionManager(history_store=store)
        await manager.cleanup()
        # cleanup() returns None, just verify no crash


class TestSessionManagerSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_no_runtime(self):
        store = StationHistoryStore()
        manager = StationSessionManager(history_store=store)
        result = await manager.snapshot()
        assert result["running"] is False
        assert result["session_id"] is None


class TestSessionManagerEvents:
    @pytest.mark.asyncio
    async def test_events_no_runtime(self):
        store = StationHistoryStore()
        store.append_session_event(
            {
                "session_id": "s1",
                "event_type": "test",
                "title": "t",
                "level": "info",
                "message": "m",
            }
        )
        manager = StationSessionManager(history_store=store)
        result = await manager.events(session_id="s1")
        assert len(result["items"]) >= 1

    @pytest.mark.asyncio
    async def test_events_with_runtime_session_id(self):
        store = StationHistoryStore()
        manager = StationSessionManager(history_store=store)
        manager._runtime = MagicMock()
        manager._runtime.session_id = "active-session"
        store.append_session_event(
            {
                "session_id": "active-session",
                "event_type": "signal",
                "title": "t",
                "level": "info",
                "message": "m",
            }
        )
        result = await manager.events()
        assert any(item.get("session_id") == "active-session" for item in result["items"])
        manager._runtime = None


class TestSessionManagerSessionHistory:
    @pytest.mark.asyncio
    async def test_session_history_empty(self, tmp_path):
        store = StationHistoryStore(base_dir=tmp_path / "history")
        manager = StationSessionManager(history_store=store)
        result = await manager.session_history()
        assert result["items"] == []


class TestDescribeEvent:
    def test_signal_event(self):
        from quantflow.web.session_manager import StationSessionManager

        title, level, _message = StationSessionManager._describe_event(
            EVENT_SIGNAL,
            {"strategy_id": "trend", "direction": 1, "symbol": "BTC/USDT", "strength": 0.8},
        )
        assert "Signal" in title
        assert level == "info"

    def test_order_filled(self):
        from quantflow.web.session_manager import StationSessionManager

        title, level, _message = StationSessionManager._describe_event(
            EVENT_ORDER,
            {"status": "filled", "side": "buy", "symbol": "BTC/USDT"},
        )
        assert "filled" in title.lower()
        assert level == "success"

    def test_order_rejected(self):
        from quantflow.web.session_manager import StationSessionManager

        title, level, _message = StationSessionManager._describe_event(
            EVENT_ORDER,
            {"status": "rejected", "side": "sell", "symbol": "ETH/USDT"},
        )
        assert "rejected" in title.lower()
        assert level == "error"

    def test_order_cancelled(self):
        from quantflow.web.session_manager import StationSessionManager

        title, level, _message = StationSessionManager._describe_event(
            EVENT_ORDER,
            {"status": "cancelled", "side": "buy", "symbol": "BTC/USDT"},
        )
        assert "cancelled" in title.lower()
        assert level == "warning"

    def test_order_submitted(self):
        from quantflow.web.session_manager import StationSessionManager

        title, level, _message = StationSessionManager._describe_event(
            EVENT_ORDER,
            {"status": "submitted", "side": "buy", "symbol": "BTC/USDT"},
        )
        assert "submitted" in title.lower()
        assert level == "info"

    def test_fill_event(self):
        from quantflow.web.session_manager import StationSessionManager

        title, level, _message = StationSessionManager._describe_event(
            EVENT_FILL,
            {"side": "buy", "quantity": 0.5, "symbol": "BTC/USDT", "price": 50000},
        )
        assert "filled" in title.lower()
        assert level == "success"

    def test_risk_event(self):
        from quantflow.web.session_manager import StationSessionManager

        title, level, _message = StationSessionManager._describe_event(
            EVENT_RISK,
            {"type": "drawdown_breach", "reason": "Max drawdown exceeded"},
        )
        assert "Risk" in title
        assert level == "warning"


class TestTelemetryPayload:
    def test_telemetry_payload(self):
        from quantflow.web.session_manager import SessionRuntime

        runtime = MagicMock(spec=SessionRuntime)
        runtime.telemetry_points = [
            {
                "timestamp": "2024-01-01T00:00:00+00:00",
                "equity": 100000,
                "cash": 50000,
                "market_value": 50000,
                "drawdown": -0.01,
                "open_positions": 1,
                "pending_orders": 0,
            },
            {
                "timestamp": "2024-01-01T00:01:00+00:00",
                "equity": 100500,
                "cash": 49900,
                "market_value": 50600,
                "drawdown": -0.005,
                "open_positions": 2,
                "pending_orders": 1,
            },
        ]
        payload = StationSessionManager._telemetry_payload(runtime)
        assert len(payload["labels"]) == 2
        assert len(payload["equity"]) == 2
        assert payload["equity"][-1] == 100500


class TestEventSummary:
    def test_event_summary(self):
        events = [
            {"event_type": "signal", "level": "info"},
            {"event_type": "order", "level": "info"},
            {"event_type": "risk", "level": "warning"},
            {"event_type": "risk", "level": "error"},
        ]
        summary = StationSessionManager._event_summary(events)
        assert summary["total"] == 4
        assert summary["by_type"]["risk"] == 2
        assert summary["by_level"]["info"] == 2


class TestGatewayConfigFromEnv:
    def test_paper_mode(self):
        from quantflow.web.session_manager import _gateway_config_from_env

        result = _gateway_config_from_env("paper", sandbox=False)
        assert result == {"sandbox": False}

    def test_live_mode_missing_env(self):
        import os

        from quantflow.web.session_manager import _gateway_config_from_env

        # Clear env vars to ensure they're missing
        for key in ["OKX_API_KEY", "OKX_SECRET", "OKX_PASSPHRASE"]:
            os.environ.pop(key, None)
        with pytest.raises(ValueError, match="Missing required"):
            _gateway_config_from_env("live", sandbox=False)

    def test_live_mode_with_env(self):
        import os

        from quantflow.web.session_manager import _gateway_config_from_env

        os.environ["OKX_API_KEY"] = "test_key"
        os.environ["OKX_SECRET"] = "test_secret"
        os.environ["OKX_PASSPHRASE"] = "test_pass"
        try:
            result = _gateway_config_from_env("live", sandbox=False)
            assert result["api_key"] == "test_key"
            assert result["secret"] == "test_secret"
            assert result["passphrase"] == "test_pass"
            assert result["sandbox"] is False
        finally:
            del os.environ["OKX_API_KEY"]
            del os.environ["OKX_SECRET"]
            del os.environ["OKX_PASSPHRASE"]


class TestSessionManagerStartConflict:
    @pytest.mark.asyncio
    async def test_start_already_running(self):
        store = StationHistoryStore()
        manager = StationSessionManager(history_store=store)
        manager._runtime = MagicMock()
        manager._runtime.loop_task = MagicMock()
        manager._runtime.loop_task.done.return_value = False
        with pytest.raises(RuntimeError, match="already running"):
            await manager.start(SessionStartRequest(mode="paper", strategies=["trend_following"]))
        manager._runtime = None


class TestSessionManagerTriggerKillSwitchNoRuntime:
    @pytest.mark.asyncio
    async def test_trigger_kill_switch_no_runtime(self):
        store = StationHistoryStore()
        manager = StationSessionManager(history_store=store)
        with pytest.raises(RuntimeError, match="No active session"):
            await manager.trigger_kill_switch("test")
