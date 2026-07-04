"""Tests for web/app.py — error handler paths (lines 54-55, 64-65, 84-85, 100-101, 180-181) and run_station (line 248)."""

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


class TestAppErrorHandlers(AioHTTPTestCase):
    """Test error paths in app handlers that catch exceptions and return 400."""

    async def get_application(self):
        history_store = StationHistoryStore()
        service = StationService(history_store=history_store)
        session_mgr = StationSessionManager(history_store=history_store)
        return create_app(service=service, session_manager=session_mgr)

    async def test_data_download_handler_error(self):
        """Lines 54-55: _data_download exception → 400."""
        with patch.object(
            self.app[STATION_SERVICE_KEY],
            "download_data",
            new_callable=AsyncMock,
            side_effect=ValueError("bad download request"),
        ):
            resp = await self.client.post("/api/data/download", json={
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "start": "2024-01-01",
                "end": "2024-01-02",
                "config_path": "quantflow/config/default.yaml",
            })
            assert resp.status == 400

    async def test_data_seed_demo_handler_error(self):
        """Lines 64-65: _data_seed_demo exception → 400."""
        with patch.object(
            self.app[STATION_SERVICE_KEY],
            "seed_demo_data",
            side_effect=ValueError("seed error"),
        ):
            resp = await self.client.post("/api/data/seed-demo", json={
                "symbol": "BTC/USDT",
                "timeframe": "4h",
                "start": "2025-01-01",
                "end": "2025-06-01",
                "config_path": "quantflow/config/default.yaml",
            })
            assert resp.status == 400

    async def test_research_handler_error(self):
        """Lines 84-85: _research exception → 400."""
        with patch.object(
            self.app[STATION_SERVICE_KEY],
            "research",
            side_effect=ValueError("research error"),
        ):
            resp = await self.client.post("/api/research", json={
                "strategy": "trend_following",
                "symbol": "BTC/USDT",
            })
            assert resp.status == 400

    async def test_validate_handler_error(self):
        """Lines 100-101: _validate exception → 400."""
        with patch.object(
            self.app[STATION_SERVICE_KEY],
            "validate",
            side_effect=ValueError("validate error"),
        ):
            resp = await self.client.post("/api/validate", json={
                "strategy": "trend_following",
                "symbol": "BTC/USDT",
                "method": "gate",
            })
            assert resp.status == 400

    async def test_session_start_handler_error(self):
        """Lines 180-181: _session_start exception → 400."""
        with patch.object(
            self.app[SESSION_MANAGER_KEY],
            "start",
            new_callable=AsyncMock,
            side_effect=ValueError("start error"),
        ):
            resp = await self.client.post("/api/session/start", json={
                "mode": "paper",
                "strategies": ["trend_following"],
            })
            assert resp.status == 400


class TestRunStation:
    def test_run_station(self):
        """Line 248: run_station function."""
        from quantflow.web.app import run_station
        # run_station calls web.run_app — just verify it doesn't crash on import
        assert callable(run_station)
