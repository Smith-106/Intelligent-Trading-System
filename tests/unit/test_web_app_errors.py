"""Tests for web/app.py — error handler paths (lines 54-55, 64-65, 84-85, 100-101, 180-181) and run_station (line 248)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import AioHTTPTestCase

from quantflow.common.redaction import REDACTED_PLACEHOLDER
from quantflow.web.app import SESSION_MANAGER_KEY, STATION_SERVICE_KEY, create_app
from quantflow.web.history import StationHistoryStore
from quantflow.web.service import StationService
from quantflow.web.session_manager import StationSessionManager


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
            resp = await self.client.post(
                "/api/data/download",
                json={
                    "symbol": "BTC/USDT",
                    "timeframe": "1h",
                    "start": "2024-01-01",
                    "end": "2024-01-02",
                    "config_path": "quantflow/config/default.yaml",
                },
            )
            assert resp.status == 400

    async def test_data_seed_demo_handler_error(self):
        """Lines 64-65: _data_seed_demo exception → 400."""
        with patch.object(
            self.app[STATION_SERVICE_KEY],
            "seed_demo_data",
            side_effect=ValueError("seed error"),
        ):
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
            assert resp.status == 400

    async def test_research_handler_error(self):
        """Lines 84-85: _research exception → 400."""
        with patch.object(
            self.app[STATION_SERVICE_KEY],
            "research",
            side_effect=ValueError("research error"),
        ):
            resp = await self.client.post(
                "/api/research",
                json={
                    "strategy": "trend_following",
                    "symbol": "BTC/USDT",
                },
            )
            assert resp.status == 400

    async def test_validate_handler_error(self):
        """Lines 100-101: _validate exception → 400."""
        with patch.object(
            self.app[STATION_SERVICE_KEY],
            "validate",
            side_effect=ValueError("validate error"),
        ):
            resp = await self.client.post(
                "/api/validate",
                json={
                    "strategy": "trend_following",
                    "symbol": "BTC/USDT",
                    "method": "gate",
                },
            )
            assert resp.status == 400

    async def test_session_start_handler_error(self):
        """Lines 180-181: _session_start exception → 400."""
        with patch.object(
            self.app[SESSION_MANAGER_KEY],
            "start",
            new_callable=AsyncMock,
            side_effect=ValueError("start error"),
        ):
            resp = await self.client.post(
                "/api/session/start",
                json={
                    "mode": "paper",
                    "strategies": ["trend_following"],
                },
            )
            assert resp.status == 400

    async def test_handler_error_does_not_leak_secret(self):
        """ISS-004/002: a service error embedding a secret value is redacted
        in the client-facing error body (single sink at _error_response)."""
        secret = "super-secret-okx-key-987654321"
        os.environ["OKX_API_KEY"] = secret
        try:
            with patch.object(
                self.app[STATION_SERVICE_KEY],
                "research",
                side_effect=ValueError(f"OKX rejected api_key={secret} (bad creds)"),
            ):
                resp = await self.client.post(
                    "/api/research",
                    json={"strategy": "trend_following", "symbol": "BTC/USDT"},
                )
                body = await resp.json()
                assert resp.status == 400
                assert secret not in body["error"]
                assert REDACTED_PLACEHOLDER in body["error"]
        finally:
            del os.environ["OKX_API_KEY"]


class TestRunStation:
    def test_run_station(self):
        """Line 248: run_station function."""
        from quantflow.web.app import run_station

        # run_station calls web.run_app — just verify it doesn't crash on import
        assert callable(run_station)


class TestResidualRiskPaths(AioHTTPTestCase):
    """ISS-20260722-004: Pinned negative tests for residual risk surfaces."""

    async def get_application(self):
        history_store = StationHistoryStore()
        service = StationService(history_store=history_store)
        session_mgr = StationSessionManager(history_store=history_store)
        return create_app(service=service, session_manager=session_mgr)

    async def test_xff_spoofing_rejected(self) -> None:
        """X-Forwarded-For header should not bypass origin check.

        The security middleware ignores XFF entirely; a cross-origin POST
        with a spoofed XFF must still be rejected (403) when Origin
        mismatches Host.
        """
        resp = await self.client.post(
            "/api/data/download",
            json={"symbol": "BTC/USDT", "timeframe": "1h"},
            headers={
                "X-Forwarded-For": "1.2.3.4",
                "Origin": "http://evil.example.com",
                "Host": "localhost:8080",
            },
        )
        # Origin mismatch → 403 regardless of XFF spoofing
        assert resp.status == 403

    async def test_dns_rebinding_rejected(self) -> None:
        """Non-loopback Host header with mismatched Origin requires rejection.

        Even when an attacker controls the Host header (DNS rebinding),
        the same_origin_guard rejects the mutation if Origin != Host.
        """
        resp = await self.client.post(
            "/api/data/download",
            json={"symbol": "BTC/USDT", "timeframe": "1h"},
            headers={
                "Host": "rebound-attacker.evil.com",
                "Origin": "http://different-origin.evil.com",
            },
        )
        # Origin != Host → 403, DNS rebinding does not bypass CSRF
        assert resp.status == 403

    async def test_static_guard_self_test(self) -> None:
        """Verify setHTML choke-point function exists in app.js.

        The setHTML function is the single audit-face for all innerHTML
        assignments. This test verifies the choke-point itself is present
        so the static guard (grep for raw `.innerHTML =` outside setHTML)
        remains effective.
        """
        app_js_path = (
            Path(__file__).resolve().parents[2] / "quantflow" / "web" / "static" / "app.js"
        )
        content = app_js_path.read_text(encoding="utf-8")
        # The setHTML choke-point function must be defined
        assert "function setHTML(node, html)" in content, (
            "setHTML choke-point function missing from app.js — "
            "static guard for innerHTML assignments is ineffective"
        )
        # The function body must contain the actual innerHTML assignment
        assert "node.innerHTML = html" in content, (
            "setHTML function body does not assign innerHTML — choke-point is hollow"
        )
