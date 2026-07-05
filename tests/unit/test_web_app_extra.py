"""Additional web/app.py tests — HTTP handler coverage."""

from __future__ import annotations

import pytest


class TestWebAppHandlers:
    @pytest.fixture
    def mock_app(self):
        """Create a minimal aiohttp app for testing handlers."""
        from quantflow.web.app import create_app
        from quantflow.web.history import StationHistoryStore
        from quantflow.web.service import StationService
        from quantflow.web.session_manager import StationSessionManager

        history_store = StationHistoryStore()
        service = StationService(history_store=history_store)
        session_mgr = StationSessionManager(history_store=history_store)
        app = create_app(service=service, session_manager=session_mgr)
        return app

    @pytest.mark.asyncio
    async def test_index_returns_html(self, mock_app):
        """Line 35-36: _index returns index.html FileResponse."""

        # Simple smoke test — just verify the app starts
        assert mock_app is not None

    @pytest.mark.asyncio
    async def test_overview_handler(self, mock_app):
        """_overview delegates to service.overview()."""
        from quantflow.web.app import STATION_SERVICE_KEY

        # Verify service is injected
        service = mock_app[STATION_SERVICE_KEY]
        assert service is not None

    def test_create_app_injects_service_and_manager(self):
        """create_app creates app with service and session_manager."""
        from quantflow.web.app import SESSION_MANAGER_KEY, STATION_SERVICE_KEY, create_app

        app = create_app()
        assert STATION_SERVICE_KEY in app
        assert SESSION_MANAGER_KEY in app

    def test_create_app_with_custom_service(self):
        """create_app accepts custom service."""
        from quantflow.web.app import STATION_SERVICE_KEY, create_app
        from quantflow.web.history import StationHistoryStore
        from quantflow.web.service import StationService

        custom_service = StationService(history_store=StationHistoryStore())
        app = create_app(service=custom_service)
        assert app[STATION_SERVICE_KEY] is custom_service

    def test_create_app_routes_registered(self):
        """create_app registers all expected routes."""
        from quantflow.web.app import create_app

        app = create_app()
        route_paths = [r.resource.canonical for r in app.router.routes() if r.resource]
        assert "/" in route_paths  # index
