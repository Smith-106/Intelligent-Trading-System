"""Tests for web layer — service.py helpers, session_manager.py helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# service.py — _safe_number, _latency_average, _timestamp_to_iso, _docker_available, _build_demo_frame
# ---------------------------------------------------------------------------


class TestServiceSafeNumber:
    def test_bool_passthrough(self):
        from quantflow.web.service import _safe_number

        assert _safe_number(True) is True
        assert _safe_number(False) is False

    def test_int_passthrough(self):
        from quantflow.web.service import _safe_number

        assert _safe_number(42) == 42

    def test_float_finite(self):
        from quantflow.web.service import _safe_number

        assert _safe_number(3.14) == pytest.approx(3.14)

    def test_float_nan_returns_none(self):
        from quantflow.web.service import _safe_number

        assert _safe_number(float("nan")) is None

    def test_float_inf_returns_none(self):
        from quantflow.web.service import _safe_number

        assert _safe_number(float("inf")) is None
        assert _safe_number(float("-inf")) is None

    def test_numpy_float_finite(self):
        from quantflow.web.service import _safe_number

        assert _safe_number(np.float64(2.5)) == pytest.approx(2.5)

    def test_numpy_float_nan(self):
        from quantflow.web.service import _safe_number

        assert _safe_number(np.float64("nan")) is None

    def test_numpy_int(self):
        from quantflow.web.service import _safe_number

        assert _safe_number(np.int64(7)) == 7

    def test_other_type_passthrough(self):
        from quantflow.web.service import _safe_number

        assert _safe_number("hello") == "hello"


class TestServiceLatencyAverage:
    def test_valid_average(self):
        from quantflow.web.service import _latency_average

        assert _latency_average(100.0, 10.0) == pytest.approx(10.0)

    def test_zero_count_returns_none(self):
        from quantflow.web.service import _latency_average

        assert _latency_average(100.0, 0) is None

    def test_nan_total_returns_none(self):
        from quantflow.web.service import _latency_average

        assert _latency_average(float("nan"), 10.0) is None

    def test_nan_count_returns_none(self):
        from quantflow.web.service import _latency_average

        assert _latency_average(100.0, float("nan")) is None

    def test_type_error_returns_none(self):
        from quantflow.web.service import _latency_average

        assert _latency_average("not_a_number", 10) is None


class TestServiceTimestampToIso:
    def test_valid_timestamp(self):
        from quantflow.web.service import _timestamp_to_iso

        result = _timestamp_to_iso(1704067200000)  # 2024-01-01
        assert result is not None
        assert "2024" in result

    def test_none_returns_none(self):
        from quantflow.web.service import _timestamp_to_iso

        assert _timestamp_to_iso(None) is None

    def test_invalid_timestamp_returns_none(self):
        from quantflow.web.service import _timestamp_to_iso

        assert _timestamp_to_iso("not_a_number") is None


class TestServiceBuildDemoFrame:
    def test_build_demo_frame_basic(self):
        from quantflow.web.service import _build_demo_frame

        df = _build_demo_frame("BTC/USDT", bars=50, timeframe="4h")
        assert not df.empty
        assert "close" in df.columns
        assert "timestamp" in df.columns
        assert len(df) == 50

    def test_build_demo_frame_with_start(self):
        from quantflow.web.service import _build_demo_frame

        df = _build_demo_frame(
            "BTC/USDT", start="2024-01-01", end="2024-06-01", bars=30, timeframe="1d"
        )
        assert not df.empty
        assert "close" in df.columns

    def test_build_demo_frame_start_after_end(self):
        """Start after end → index generated with periods."""
        from quantflow.web.service import _build_demo_frame

        df = _build_demo_frame(
            "BTC/USDT", start="2025-01-01", end="2024-01-01", bars=10, timeframe="4h"
        )
        # Should still produce a frame (periods-based fallback)
        assert not df.empty


class TestServiceToJsonable:
    def test_dict_conversion(self):
        from quantflow.web.service import _to_jsonable

        result = _to_jsonable({"a": 1, "b": float("nan")})
        assert result["a"] == 1
        assert result["b"] is None

    def test_list_conversion(self):
        from quantflow.web.service import _to_jsonable

        result = _to_jsonable([1, float("inf"), "hello"])
        assert result[0] == 1
        assert result[1] is None
        assert result[2] == "hello"

    def test_path_conversion(self):
        from quantflow.web.service import _to_jsonable

        result = _to_jsonable(Path("/tmp/test"))
        assert isinstance(result, str)

    def test_nested_conversion(self):
        from quantflow.web.service import _to_jsonable

        result = _to_jsonable({"outer": {"inner": float("nan")}})
        assert result["outer"]["inner"] is None


# ---------------------------------------------------------------------------
# session_manager.py — _safe_number, _jsonable, _format_duration, _gateway_config_from_env
# ---------------------------------------------------------------------------


class TestSessionManagerSafeNumber:
    def test_float_finite(self):
        from quantflow.web.session_manager import _safe_number

        assert _safe_number(3.14) == pytest.approx(3.14)

    def test_float_nan(self):
        from quantflow.web.session_manager import _safe_number

        assert _safe_number(float("nan")) is None

    def test_float_inf(self):
        from quantflow.web.session_manager import _safe_number

        assert _safe_number(float("inf")) is None


class TestSessionManagerJsonable:
    def test_dict(self):
        from quantflow.web.session_manager import _jsonable

        result = _jsonable({"a": 1})
        assert result == {"a": 1}

    def test_list(self):
        from quantflow.web.session_manager import _jsonable

        result = _jsonable([1, 2])
        assert result == [1, 2]

    def test_set(self):
        from quantflow.web.session_manager import _jsonable

        result = _jsonable({1, 2})
        assert sorted(result) == [1, 2]

    def test_path(self):
        from quantflow.web.session_manager import _jsonable

        result = _jsonable(Path("/tmp"))
        assert isinstance(result, str)

    def test_nan_to_none(self):
        from quantflow.web.session_manager import _jsonable

        result = _jsonable(float("nan"))
        assert result is None


class TestSessionManagerFormatDuration:
    def test_seconds_only(self):
        from quantflow.web.session_manager import _format_duration

        assert _format_duration(45) == "45s"

    def test_minutes_and_seconds(self):
        from quantflow.web.session_manager import _format_duration

        assert _format_duration(125) == "2m 05s"

    def test_hours_minutes(self):
        from quantflow.web.session_manager import _format_duration

        assert _format_duration(3665) == "1h 01m"

    def test_negative_clamps_to_zero(self):
        from quantflow.web.session_manager import _format_duration

        assert _format_duration(-5) == "0s"


class TestSessionManagerGatewayConfig:
    def test_paper_mode(self):
        """Paper mode returns sandbox config."""
        from quantflow.web.session_manager import _gateway_config_from_env

        config = _gateway_config_from_env("paper", sandbox=False)
        assert "sandbox" in config

    def test_live_mode_missing_env_vars(self):
        """Live mode with missing env vars raises ValueError."""
        from quantflow.web.session_manager import _gateway_config_from_env

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="OKX_API_KEY"):
                _gateway_config_from_env("live", sandbox=False)

    def test_live_mode_with_env_vars(self):
        """Live mode with env vars returns full config."""
        from quantflow.web.session_manager import _gateway_config_from_env

        env = {
            "OKX_API_KEY": "test_key",
            "OKX_SECRET": "test_secret",
            "OKX_PASSPHRASE": "test_pass",
        }
        with patch.dict("os.environ", env, clear=True):
            config = _gateway_config_from_env("live", sandbox=False)
            assert config["api_key"] == "test_key"
            assert config["secret"] == "test_secret"
            assert config["passphrase"] == "test_pass"


class TestSessionManagerSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_with_no_runtime(self):
        """snapshot() with no active runtime returns empty-ish state."""
        from quantflow.web.session_manager import StationSessionManager

        manager = StationSessionManager()
        result = await manager.snapshot()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_stop_with_no_runtime(self):
        """stop() with no active runtime returns error dict."""
        from quantflow.web.session_manager import StationSessionManager

        manager = StationSessionManager()
        result = await manager.stop()
        assert isinstance(result, dict)
