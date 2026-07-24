"""Tests for web/app.py — HTTP handler coverage via aiohttp test utilities."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer

from quantflow.web.app import SESSION_MANAGER_KEY, STATION_SERVICE_KEY, create_app
from quantflow.web.history import StationHistoryStore
from quantflow.web.service import StationService
from quantflow.web.session_manager import StationSessionManager


class TestAppHandlers(AioHTTPTestCase):
    async def get_application(self):
        history_store = StationHistoryStore()
        service = StationService(history_store=history_store)
        session_mgr = StationSessionManager(history_store=history_store)
        return create_app(service=service, session_manager=session_mgr)

    async def test_overview_handler(self):
        resp = await self.client.get("/api/overview")
        assert resp.status == 200
        data = await resp.json()
        assert isinstance(data, dict)
        assert "version" in data

    async def test_strategies_handler(self):
        resp = await self.client.get("/api/strategies")
        assert resp.status == 200
        data = await resp.json()
        assert isinstance(data, list)

    async def test_data_snapshot_handler(self):
        resp = await self.client.get("/api/data")
        assert resp.status == 200
        data = await resp.json()
        assert isinstance(data, dict)

    async def test_research_history_handler(self):
        resp = await self.client.get("/api/research/history")
        assert resp.status == 200
        data = await resp.json()
        assert "items" in data

    async def test_validation_history_handler(self):
        resp = await self.client.get("/api/validate/history")
        assert resp.status == 200
        data = await resp.json()
        assert "items" in data

    async def test_workbench_state_get_handler(self):
        resp = await self.client.get("/api/workbench/state")
        assert resp.status == 200
        data = await resp.json()
        assert "state" in data

    async def test_workbench_state_post_handler(self):
        resp = await self.client.post("/api/workbench/state", json={"panel": "execution"})
        assert resp.status == 200
        data = await resp.json()
        assert "state" in data

    async def test_workbench_state_post_invalid(self):
        resp = await self.client.post("/api/workbench/state", json="not_a_dict")
        assert resp.status == 400

    async def test_monitoring_handler(self):
        resp = await self.client.get("/api/monitoring")
        assert resp.status == 200
        data = await resp.json()
        assert isinstance(data, dict)
        assert "health" in data

    async def test_execution_handler(self):
        resp = await self.client.get("/api/execution")
        assert resp.status == 200
        data = await resp.json()
        assert isinstance(data, dict)
        assert "status" in data

    async def test_session_snapshot_handler(self):
        resp = await self.client.get("/api/session")
        assert resp.status == 200
        data = await resp.json()
        assert isinstance(data, dict)

    async def test_session_events_handler(self):
        resp = await self.client.get("/api/session/events")
        assert resp.status == 200
        data = await resp.json()
        assert isinstance(data, dict)

    async def test_session_history_handler(self):
        resp = await self.client.get("/api/session/history")
        assert resp.status == 200
        data = await resp.json()
        assert isinstance(data, dict)

    async def test_session_stop_handler(self):
        resp = await self.client.post("/api/session/stop")
        assert resp.status == 200
        data = await resp.json()
        assert isinstance(data, dict)

    async def test_kill_switch_handler_no_runtime(self):
        resp = await self.client.post("/api/session/kill-switch", json={"reason": "test"})
        assert resp.status == 400

    async def test_seed_demo_handler(self):
        resp = await self.client.post(
            "/api/data/seed-demo",
            json={
                "symbol": "BTC/USDT",
                "timeframe": "4h",
                "start": "2025-01-01",
                "end": "2025-06-01",
                "config_path": "quantflow/config/default.yaml",
            },
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["data_source"] == "demo"

    async def test_tag_source_handler_invalid(self):
        resp = await self.client.post(
            "/api/data/tag-source",
            json={
                "symbol": "BTC/USDT",
                "data_source": "invalid_source",
            },
        )
        assert resp.status == 400

    async def test_research_handler(self):
        resp = await self.client.post(
            "/api/research",
            json={
                "strategy": "trend_following",
                "symbol": "BTC/USDT",
            },
        )
        assert resp.status == 200
        data = await resp.json()
        assert "result" in data

    async def test_validate_handler(self):
        resp = await self.client.post(
            "/api/validate",
            json={
                "strategy": "trend_following",
                "symbol": "BTC/USDT",
                "method": "gate",
            },
        )
        assert resp.status == 200
        data = await resp.json()
        assert "method" in data

    async def test_overview_response_does_not_leak_internal_paths(self):
        # ISS-036 (CWE-200): overview must not expose parquet_dir /
        # duckdb_path / config_path / redis_url to any authenticated viewer.
        # They reveal the install prefix + user directory. Recursively check
        # the whole response tree (paths can nest under data/).
        leaked = {"parquet_dir", "duckdb_path", "config_path", "redis_url"}

        def _walk(value):
            if isinstance(value, dict):
                assert not (set(value) & leaked), f"leaked keys: {set(value) & leaked}"
                for v in value.values():
                    _walk(v)
            elif isinstance(value, list):
                for item in value:
                    _walk(item)

        resp = await self.client.get("/api/overview")
        assert resp.status == 200
        _walk(await resp.json())

    async def test_data_snapshot_and_monitoring_do_not_leak_internal_paths(self):
        # ISS-036: the same fields were also leaked by data_snapshot (which
        # re-emits overview's paths in a storage block) and monitoring (which
        # copies config_path into its platform block).
        leaked = {"parquet_dir", "duckdb_path", "config_path", "redis_url"}

        def _walk(value):
            if isinstance(value, dict):
                assert not (set(value) & leaked), f"leaked keys: {set(value) & leaked}"
                for v in value.values():
                    _walk(v)
            elif isinstance(value, list):
                for item in value:
                    _walk(item)

        for endpoint in ("/api/data", "/api/monitoring"):
            resp = await self.client.get(endpoint)
            assert resp.status == 200
            _walk(await resp.json())


class TestAppCreate:
    def test_create_app_default(self):
        app = create_app()
        assert STATION_SERVICE_KEY in app
        assert SESSION_MANAGER_KEY in app

    def test_create_app_routes(self):
        app = create_app()
        route_paths = [r.resource.canonical for r in app.router.routes() if r.resource]
        assert "/" in route_paths
        assert "/api/overview" in route_paths
        assert "/api/strategies" in route_paths

    def test_cleanup_hook(self):
        app = create_app()
        # on_cleanup should have our handler registered
        assert len(app.on_cleanup) > 0


class TestStationAuthAndCSRF:
    """SEC-002 (no auth) + SEC-004 (Origin-bypass) fix verification."""

    async def _post(self, client, path, *, headers=None, json_body=None):
        return await client.post(path, json=json_body, headers=headers or {})

    async def test_mutation_allowed_without_token_on_loopback(self):
        """No token set + loopback TestClient → mutation allowed (back-compat)."""
        history_store = StationHistoryStore()
        app = create_app(
            service=StationService(history_store=history_store),
            session_manager=StationSessionManager(history_store=history_store),
        )
        async with TestClient(TestServer(app)) as client:
            # Same-origin (TestClient sends matching Host/Origin by default).
            resp = await self._post(client, "/api/session/stop")
            assert resp.status == 200

    async def test_mutation_blocked_when_token_set_and_missing(self, monkeypatch):
        """SEC-002: with QUANTFLOW_STATION_TOKEN set, missing Authorization → 401."""
        monkeypatch.setenv("QUANTFLOW_STATION_TOKEN", "secret-token-value-123")
        history_store = StationHistoryStore()
        app = create_app(
            service=StationService(history_store=history_store),
            session_manager=StationSessionManager(history_store=history_store),
        )
        async with TestClient(TestServer(app)) as client:
            resp = await self._post(client, "/api/session/stop")
            assert resp.status == 401

    async def test_mutation_blocked_with_wrong_token(self, monkeypatch):
        """SEC-002: wrong token → 401."""
        monkeypatch.setenv("QUANTFLOW_STATION_TOKEN", "secret-token-value-123")
        history_store = StationHistoryStore()
        app = create_app(
            service=StationService(history_store=history_store),
            session_manager=StationSessionManager(history_store=history_store),
        )
        async with TestClient(TestServer(app)) as client:
            resp = await self._post(
                client,
                "/api/session/stop",
                headers={"Authorization": "Bearer wrong-token"},
            )
            assert resp.status == 401

    async def test_mutation_allowed_with_correct_token(self, monkeypatch):
        """SEC-002: correct Bearer token → mutation passes auth (then CSRF check)."""
        monkeypatch.setenv("QUANTFLOW_STATION_TOKEN", "secret-token-value-123")
        history_store = StationHistoryStore()
        app = create_app(
            service=StationService(history_store=history_store),
            session_manager=StationSessionManager(history_store=history_store),
        )
        async with TestClient(TestServer(app)) as client:
            resp = await self._post(
                client,
                "/api/session/stop",
                headers={"Authorization": "Bearer secret-token-value-123"},
            )
            assert resp.status == 200

    async def test_cross_origin_mutation_blocked_without_custom_header(self):
        """SEC-004: cross-origin POST (Origin != Host, no custom header) → 403.
        A browser-driven CSRF sends a mismatched Origin; the Station rejects it."""
        history_store = StationHistoryStore()
        app = create_app(
            service=StationService(history_store=history_store),
            session_manager=StationSessionManager(history_store=history_store),
        )
        async with TestClient(TestServer(app)) as client:
            # Origin is a foreign host; Host is the real server address.
            resp = await self._post(
                client,
                "/api/session/stop",
                headers={"Origin": "https://evil.example.com"},
            )
            assert resp.status == 403

    async def test_cross_origin_mutation_blocked_even_with_custom_header(self):
        """REV-001: X-Requested-With is NOT a forbidden CORS header, so any
        cross-origin fetch can set it. The CSRF guard must NOT accept its mere
        presence as a same-origin signal — a cross-origin POST with
        X-Requested-With is still blocked (403)."""
        history_store = StationHistoryStore()
        app = create_app(
            service=StationService(history_store=history_store),
            session_manager=StationSessionManager(history_store=history_store),
        )
        async with TestClient(TestServer(app)) as client:
            resp = await self._post(
                client,
                "/api/session/stop",
                headers={
                    "Origin": "https://evil.example.com",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
            assert resp.status == 403

    async def test_valid_token_does_not_skip_csrf_for_cross_origin(self, monkeypatch):
        """REV-002: a valid Bearer token does NOT bypass the CSRF check — the
        two controls are orthogonal (auth=who, CSRF=browser intent). A valid
        token + mismatched Origin is still 403."""
        monkeypatch.setenv("QUANTFLOW_STATION_TOKEN", "secret-token-value-123")
        history_store = StationHistoryStore()
        app = create_app(
            service=StationService(history_store=history_store),
            session_manager=StationSessionManager(history_store=history_store),
        )
        async with TestClient(TestServer(app)) as client:
            resp = await self._post(
                client,
                "/api/session/stop",
                headers={
                    "Authorization": "Bearer secret-token-value-123",
                    "Origin": "https://evil.example.com",
                },
            )
            assert resp.status == 403

    async def test_origin_absent_allowed_non_browser(self):
        """SEC-004: absent Origin (non-browser client like the TestClient) is
        allowed — such clients already have local access in the single-operator
        threat model; network exposure is governed by the token control."""
        history_store = StationHistoryStore()
        app = create_app(
            service=StationService(history_store=history_store),
            session_manager=StationSessionManager(history_store=history_store),
        )
        async with TestClient(TestServer(app)) as client:
            resp = await self._post(client, "/api/session/stop")
            assert resp.status == 200

    async def test_get_endpoints_not_blocked_by_auth(self, monkeypatch):
        """Read-only GETs must remain open even when a token is set."""
        monkeypatch.setenv("QUANTFLOW_STATION_TOKEN", "secret-token-value-123")
        history_store = StationHistoryStore()
        app = create_app(
            service=StationService(history_store=history_store),
            session_manager=StationSessionManager(history_store=history_store),
        )
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/overview")
            assert resp.status == 200


class TestRunStationNonLoopbackGuard:
    """SEC-002: run_station must refuse non-loopback bind without a token."""

    def test_refuses_non_loopback_without_token(self, monkeypatch):
        monkeypatch.delenv("QUANTFLOW_STATION_TOKEN", raising=False)
        from quantflow.web.app import run_station

        with pytest.raises(RuntimeError, match="non-loopback"):
            run_station(host="0.0.0.0", port=8088)

    def test_allows_non_loopback_with_token(self, monkeypatch):
        monkeypatch.setenv("QUANTFLOW_STATION_TOKEN", "secret-token-value-123")
        from quantflow.web.app import _is_loopback_host, _station_token

        # Not actually starting the server — just confirming the guard passes.
        assert not _is_loopback_host("0.0.0.0")
        assert _station_token() == "secret-token-value-123"

    @pytest.mark.parametrize(
        "host,expected",
        [
            ("127.0.0.1", True),
            ("localhost", True),
            ("0.0.0.0", False),
            ("::1", True),
            ("192.168.1.5", False),
            ("", False),
        ],
    )
    def test_is_loopback_host(self, host, expected):
        from quantflow.web.app import _is_loopback_host

        assert _is_loopback_host(host) is expected
