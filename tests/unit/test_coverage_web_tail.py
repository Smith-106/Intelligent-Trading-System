"""Web tail coverage: history/security/rate_limit/app/service/session_manager."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from quantflow.web.app import create_app
from quantflow.web.history import StationHistoryStore, _MAX_JSONL_BYTES
from quantflow.web.rate_limit import RateLimiter, _client_key
from quantflow.web.security import _is_loopback_host, same_origin_guard
from quantflow.web.service import (
    StationService,
    _query_symbol_frame,
    _validate_params_depth,
)
from quantflow.web.session_manager import StationSessionManager


# ------------------------------------------------------------------- history
class TestHistoryTail:
    def test_append_research_summary_not_dict(self, tmp_path: pytest.TempPathFactory) -> None:
        """L78: summary not a dict → synthesized summary."""
        store = StationHistoryStore(base_dir=tmp_path / "h")
        rec = store.append_research_run({"result": {"decision": "GO"}, "summary": "plain"})
        assert rec["record_id"]

    def test_load_workbench_state_non_dict(self, tmp_path: pytest.TempPathFactory) -> None:
        """L144: workbench_state.json exists but data not a dict → None."""
        store = StationHistoryStore(base_dir=tmp_path / "h")
        store.save_workbench_state({"a": 1})
        (tmp_path / "h" / "workbench_state.json").write_text("[1,2]", encoding="utf-8")
        assert store.load_workbench_state() is None

    def test_append_triggers_rotate(self, tmp_path: pytest.TempPathFactory) -> None:
        """L169: file exceeds cap → _rotate truncates."""
        store = StationHistoryStore(base_dir=tmp_path / "h")
        path = tmp_path / "h" / "session_events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write a file larger than the cap.
        with path.open("w", encoding="utf-8") as fh:
            fh.write("x" * (_MAX_JSONL_BYTES + 1024) + "\n")
        store.append_session_event({"session_id": "s1", "event_type": "signal"})
        assert path.stat().st_size <= _MAX_JSONL_BYTES

    def test_append_rotate_oserror(self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
        """L170-171: path.stat() OSError → pass."""
        store = StationHistoryStore(base_dir=tmp_path / "h")
        monkeypatch.setattr(
            "quantflow.web.history.Path.stat",
            lambda self: (_ for _ in ()).throw(OSError("boom")),
        )
        store.append_session_event({"session_id": "s1", "event_type": "signal"})

    def test_list_missing_category(self, tmp_path: pytest.TempPathFactory) -> None:
        """L234: category file missing → []."""
        store = StationHistoryStore(base_dir=tmp_path / "h")
        assert store.list_session_events(limit=5, session_id="nope") == []

    def test_list_skips_blank_and_corrupt_lines(self, tmp_path: pytest.TempPathFactory) -> None:
        """L245-257: blank/corrupt lines skipped."""
        store = StationHistoryStore(base_dir=tmp_path / "h")
        path = tmp_path / "h" / "session_events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n{not-json}\n\n", encoding="utf-8")
        assert store.list_session_events(limit=5) == []

    def test_read_tail_multiple_chunks(self, tmp_path: pytest.TempPathFactory) -> None:
        """L269-291: multi-chunk tail read."""
        store = StationHistoryStore(base_dir=tmp_path / "h")
        path = tmp_path / "h" / "session_events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps({"i": i}) for i in range(2000)]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tail = store._read_tail_lines(path, max_lines=50)
        assert len(tail) == 50
        non_blank = [l for l in tail if l.strip()]
        assert json.loads(non_blank[-1])["i"] == 1999


# ------------------------------------------------------------------- security
class TestSecurityTail:
    def test_is_loopback_ip(self) -> None:
        """L66-67: loopback IP (127.0.0.1 / ::1) → True."""
        assert _is_loopback_host("127.0.0.1") is True
        assert _is_loopback_host("[::1]") is True

    def test_same_origin_invalid_url(self) -> None:
        """L122-123: urlparse ValueError → origin_host empty → 403."""

        async def run() -> None:
            request = SimpleNamespace(
                method="POST",
                headers={"Origin": "http://[::1", "Host": "localhost:8080"},
                app={},
            )
            resp = await same_origin_guard(request, lambda r: web.Response(text="ok"))
            assert resp.status == 403

        import asyncio

        asyncio.run(run())


# ------------------------------------------------------------------ rate_limit
class TestRateLimitTail:
    def test_retry_after_no_bucket(self) -> None:
        """L98-99: no bucket → 0.0."""
        limiter = RateLimiter(capacity=3.0, refill_per_sec=1.0)
        assert limiter.retry_after("nobody") == 0.0

    def test_client_key_unknown(self) -> None:
        """L115-117: no forwarded, no peername → 'unknown'."""
        request = SimpleNamespace(
            headers={}, transport=SimpleNamespace(get_extra_info=lambda k: None)
        )
        assert _client_key(request) == "unknown"


# ------------------------------------------------------------------------ app
class TestAppTail:
    async def _client(self) -> TestClient:
        store = StationHistoryStore(base_dir="data/station_history_test_tail")
        service = StationService(history_store=store)
        app = create_app(service=service)
        return TestClient(TestServer(app))

    async def test_invalid_limit_param(self) -> None:
        """L56-57: non-integer limit → 400."""
        client = await self._client()
        async with client:
            resp = await client.get("/api/research/history?limit=abc")
            assert resp.status == 400

    async def test_negative_limit_clamped(self) -> None:
        """L61-62: negative limit → 0."""
        client = await self._client()
        async with client:
            resp = await client.get("/api/research/history?limit=-5")
            assert resp.status == 200

    async def test_kill_switch_non_dict_payload(self) -> None:
        """L294-295: non-dict payload → 400."""
        client = await self._client()
        async with client:
            resp = await client.post("/api/session/kill-switch", data="[1,2]")
            assert resp.status == 400


# ---------------------------------------------------------------------- service
class TestServiceTail:
    def test_validate_params_depth_none(self) -> None:
        """L63-64: value None → None."""
        assert _validate_params_depth(None) is None

    def test_validate_params_depth_list(self) -> None:
        """L78-85: list/tuple branch."""
        with pytest.raises(ValueError, match="too many keys"):
            _validate_params_depth({"a": [{"b": 1} for _ in range(1000)]})

    def test_query_symbol_frame_data_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L615-617: DataError → demo frame."""
        from quantflow.data.store import DataError

        fake_store = MagicMock()
        fake_store.query = MagicMock(side_effect=DataError("corrupt"))
        frame, tag = _query_symbol_frame(fake_store, "BTC/USDT")
        assert tag == "demo"
        assert not frame.empty

    def test_save_workbench_state_not_serializable(self, tmp_path: pytest.TempPathFactory) -> None:
        """L1367-1368: non-serializable payload → ValueError."""
        store = StationHistoryStore(base_dir=tmp_path / "h")
        service = StationService(history_store=store)
        with pytest.raises(ValueError, match="not JSON-serializable"):
            service.save_workbench_state({"bad": object()})


# ------------------------------------------------------------------------ app
class TestAppTail2:
    async def test_index_404_when_dist_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L123-125: dist index missing → 404."""
        from quantflow.web import app as app_mod

        store = StationHistoryStore(base_dir="data/station_history_test_tail2")
        service = StationService(history_store=store)
        monkeypatch.setattr(
            app_mod, "_dist_dir", lambda: app_mod._static_dir() / "no-such-dist"
        )
        client = TestClient(TestServer(create_app(service=service)))
        async with client:
            resp = await client.get("/")
            assert resp.status == 404

    async def test_spa_fallback_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L130: SPA fallback → _index → 404 when dist missing."""
        from quantflow.web import app as app_mod

        store = StationHistoryStore(base_dir="data/station_history_test_tail2")
        service = StationService(history_store=store)
        monkeypatch.setattr(
            app_mod, "_dist_dir", lambda: app_mod._static_dir() / "no-such-dist"
        )
        client = TestClient(TestServer(create_app(service=service)))
        async with client:
            resp = await client.get("/some/spa/route")
            assert resp.status == 404

    def test_create_app_with_dist_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory) -> None:
        """L372-375: dist_dir exists → static route added."""
        from quantflow.web import app as app_mod

        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html></html>", encoding="utf-8")
        store = StationHistoryStore(base_dir=tmp_path / "h")
        service = StationService(history_store=store)
        monkeypatch.setattr(app_mod, "_dist_dir", lambda: dist)
        app = create_app(service=service)
        assert any(r.resource and "dist" in str(r.resource) for r in app.router.routes())


# ------------------------------------------------------------- session_manager
class TestSessionManagerTail:
    @pytest.mark.asyncio
    async def test_start_kill_switch_required(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L167-168: live mode without kill switch → ValueError."""
        from quantflow.common.config import AppConfig
        from quantflow.web.session_manager import SessionStartRequest

        store = StationHistoryStore(base_dir=tmp_path / "h")
        mgr = StationSessionManager(history_store=store)
        cfg = AppConfig()
        cfg.execution.mode = "live"
        cfg.risk.kill_switch_enabled = False
        monkeypatch.setattr(
            "quantflow.web.session_manager.load_config", lambda *a, **k: cfg
        )
        req = SessionStartRequest(mode="live", symbol="BTC/USDT")
        with pytest.raises(ValueError, match="Kill switch"):
            await mgr.start(req)

    @pytest.mark.asyncio
    async def test_snapshot_runtime_none(self, tmp_path: pytest.TempPathFactory) -> None:
        """L322-324: runtime None → empty snapshot."""
        store = StationHistoryStore(base_dir=tmp_path / "h")
        mgr = StationSessionManager(history_store=store)
        snap = await mgr.snapshot()
        assert snap["session_id"] is None

    @pytest.mark.asyncio
    async def test_stop_with_active_tasks(self, tmp_path: pytest.TempPathFactory) -> None:
        """L246-250 / L263-267: active loop_task + flush_task cancelled."""
        from quantflow.web.session_manager import SessionRuntime, SessionStartRequest

        store = StationHistoryStore(base_dir=tmp_path / "h")
        mgr = StationSessionManager(history_store=store)
        runtime = MagicMock(spec=SessionRuntime)
        runtime.loop_task = asyncio.create_task(asyncio.sleep(3600))
        runtime.session = MagicMock()
        runtime.session.last_error = ""
        runtime.session.stop = AsyncMock()
        runtime.session.snapshot_state = MagicMock(
            return_value={
                "health": {"running": False},
                "portfolio": {"total_value": 0.0, "cash": 0.0, "drawdown": 0.0, "positions": 0},
                "positions": [],
                "open_orders": [],
                "kill_switch": None,
            }
        )
        runtime.flush_task = asyncio.create_task(asyncio.sleep(3600))
        runtime.session_id = "s1"
        runtime.started_at = "2024-01-01T00:00:00Z"
        runtime.operator_id = "op"
        runtime.request = SessionStartRequest(mode="paper", symbol="BTC/USDT")
        runtime.last_error = None
        runtime.pending_events = []
        runtime.telemetry_points = []
        runtime.event_handlers = []
        flush_task = runtime.flush_task
        mgr._runtime = runtime
        snap = await mgr.stop()
        assert snap["session_id"] == "s1"
        assert flush_task.cancelled()

    @pytest.mark.asyncio
    async def test_stop_with_done_tasks(self, tmp_path: pytest.TempPathFactory) -> None:
        """L246-250 / L263-267: loop_task done + flush_task None → skip cancel."""
        from quantflow.web.session_manager import SessionRuntime, SessionStartRequest

        store = StationHistoryStore(base_dir=tmp_path / "h")
        mgr = StationSessionManager(history_store=store)
        runtime = MagicMock(spec=SessionRuntime)
        done_task = asyncio.create_task(asyncio.sleep(0))
        await done_task
        runtime.loop_task = done_task
        runtime.session = MagicMock()
        runtime.session.last_error = ""
        runtime.session.stop = AsyncMock()
        runtime.session.snapshot_state = MagicMock(
            return_value={
                "health": {"running": False},
                "portfolio": {"total_value": 0.0, "cash": 0.0, "drawdown": 0.0, "positions": 0},
                "positions": [],
                "open_orders": [],
                "kill_switch": None,
            }
        )
        runtime.flush_task = None
        runtime.session_id = "s3"
        runtime.started_at = "2024-01-01T00:00:00Z"
        runtime.operator_id = "op"
        runtime.request = SessionStartRequest(mode="paper", symbol="BTC/USDT")
        runtime.last_error = None
        runtime.pending_events = []
        runtime.telemetry_points = []
        runtime.event_handlers = []
        mgr._runtime = runtime
        snap = await mgr.stop()
        assert snap["session_id"] == "s3"

    @pytest.mark.asyncio
    async def test_snapshot_with_runtime(self, tmp_path: pytest.TempPathFactory) -> None:
        """L322-324 / L394-395: runtime present → built snapshot; kill_switch None default."""
        from quantflow.web.session_manager import SessionRuntime, SessionStartRequest

        store = StationHistoryStore(base_dir=tmp_path / "h")
        mgr = StationSessionManager(history_store=store)
        runtime = MagicMock(spec=SessionRuntime)
        runtime.loop_task = MagicMock()
        runtime.loop_task.done.return_value = True
        runtime.session = MagicMock()
        runtime.session.last_error = ""
        runtime.session.snapshot_state = MagicMock(
            return_value={
                "health": {"running": True},
                "portfolio": {"total_value": 100.0, "cash": 50.0, "drawdown": 0.0, "positions": 1},
                "positions": [],
                "open_orders": [],
                "kill_switch": None,
            }
        )
        runtime.session_id = "s2"
        runtime.started_at = "2024-01-01T00:00:00Z"
        runtime.operator_id = "op"
        runtime.request = SessionStartRequest(mode="paper", symbol="BTC/USDT")
        runtime.last_error = None
        runtime.pending_events = []
        runtime.telemetry_points = []
        runtime.event_handlers = []
        mgr._runtime = runtime
        snap = await mgr.snapshot()
        assert snap["session_id"] == "s2"
        assert snap["kill_switch"] == {"active": False, "reason": None}
