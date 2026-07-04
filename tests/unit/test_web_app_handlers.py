"""Tests for web/app.py — HTTP handler coverage via aiohttp test utilities."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer

from quantflow.web.app import create_app, STATION_SERVICE_KEY, SESSION_MANAGER_KEY
from quantflow.web.service import StationService
from quantflow.web.session_manager import StationSessionManager
from quantflow.web.history import StationHistoryStore


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
        resp = await self.client.post("/api/data/seed-demo", json={
            "symbol": "BTC/USDT",
            "timeframe": "4h",
            "start": "2025-01-01",
            "end": "2025-06-01",
            "config_path": "quantflow/config/default.yaml",
        })
        assert resp.status == 200
        data = await resp.json()
        assert data["data_source"] == "demo"

    async def test_tag_source_handler_invalid(self):
        resp = await self.client.post("/api/data/tag-source", json={
            "symbol": "BTC/USDT",
            "data_source": "invalid_source",
        })
        assert resp.status == 400

    async def test_research_handler(self):
        resp = await self.client.post("/api/research", json={
            "strategy": "trend_following",
            "symbol": "BTC/USDT",
        })
        assert resp.status == 200
        data = await resp.json()
        assert "result" in data

    async def test_validate_handler(self):
        resp = await self.client.post("/api/validate", json={
            "strategy": "trend_following",
            "symbol": "BTC/USDT",
            "method": "gate",
        })
        assert resp.status == 200
        data = await resp.json()
        assert "method" in data


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
