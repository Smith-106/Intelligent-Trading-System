"""Aiohttp application for QuantFlow Station."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from aiohttp import web

from quantflow.common.exceptions import DataError, GatewayConnectionError
from quantflow.web.history import StationHistoryStore
from quantflow.web.service import (
    DataDownloadRequest,
    DataSourceTagRequest,
    ResearchRequest,
    StationService,
    ValidationRequest,
)
from quantflow.web.session_manager import SessionStartRequest, StationSessionManager

STATIC_PACKAGE = "quantflow.web.static"
STATION_SERVICE_KEY = web.AppKey("station_service", StationService)
SESSION_MANAGER_KEY = web.AppKey("session_manager", StationSessionManager)

# Local-only station: mutation endpoints must come from the same origin to
# prevent browser-driven CSRF (a random web page posting to
# /api/session/kill-switch on localhost). Read-only GETs are exempt.
_MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _parse_limit(request: web.Request, default: int = 12, maximum: int = 500) -> int:
    """Parse the ``limit`` query param defensively, clamped to [0, maximum]."""
    raw = request.query.get("limit", str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(
            text='{"error":"invalid limit"}',
            content_type="application/json",
        ) from exc
    if value < 0:
        return 0
    return min(value, maximum)


@web.middleware
async def _same_origin_guard(request: web.Request, handler):
    """Reject cross-origin mutations to local trading-control endpoints.

    aiohttp does not check Origin/Referer by default, so a page in the
    operator's browser could issue a cross-site POST to start a live session
    or flip the kill switch. Requiring a same-origin header (or a matching
    local Host) for mutating methods blocks browser-driven CSRF without a
    token, while still allowing same-origin fetches from the Station UI and
    non-browser clients (which simply omit the header).
    """
    if request.method in _MUTATION_METHODS:
        origin = request.headers.get("Origin")
        if origin:
            host = request.headers.get("Host", "")
            # Origin is scheme://host[:port]; compare the host portion.
            try:
                from urllib.parse import urlparse

                origin_host = urlparse(origin).netloc
            except Exception:
                origin_host = ""
            if origin_host and host and origin_host != host:
                return web.json_response(
                    {"error": "cross-origin mutations are not permitted"},
                    status=403,
                )
    return await handler(request)


def _static_dir() -> Path:
    return Path(resources.files(STATIC_PACKAGE))


async def _index(_: web.Request) -> web.FileResponse:
    return web.FileResponse(_static_dir() / "index.html")


async def _overview(request: web.Request) -> web.Response:
    service = request.app[STATION_SERVICE_KEY]
    return web.json_response(service.overview())


async def _strategies(request: web.Request) -> web.Response:
    service = request.app[STATION_SERVICE_KEY]
    return web.json_response(service.strategies())


async def _data_snapshot(request: web.Request) -> web.Response:
    service = request.app[STATION_SERVICE_KEY]
    return web.json_response(service.data_snapshot())


async def _data_download(request: web.Request) -> web.Response:
    service = request.app[STATION_SERVICE_KEY]
    payload = await request.json()
    try:
        result = await service.download_data(DataDownloadRequest.model_validate(payload))
    except (ValueError, DataError, GatewayConnectionError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response(result)


async def _data_seed_demo(request: web.Request) -> web.Response:
    service = request.app[STATION_SERVICE_KEY]
    payload = await request.json()
    try:
        result = service.seed_demo_data(DataDownloadRequest.model_validate(payload))
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response(result)


async def _data_tag_source(request: web.Request) -> web.Response:
    service = request.app[STATION_SERVICE_KEY]
    payload = await request.json()
    try:
        result = service.tag_data_source(DataSourceTagRequest.model_validate(payload))
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response(result)


async def _research(request: web.Request) -> web.Response:
    service = request.app[STATION_SERVICE_KEY]
    payload = await request.json()
    try:
        result = service.research(ResearchRequest.model_validate(payload))
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response(result)


async def _research_history(request: web.Request) -> web.Response:
    service = request.app[STATION_SERVICE_KEY]
    limit = _parse_limit(request, default=12)
    return web.json_response({"items": service.research_history(limit=limit)})


async def _validate(request: web.Request) -> web.Response:
    service = request.app[STATION_SERVICE_KEY]
    payload = await request.json()
    try:
        result = service.validate(ValidationRequest.model_validate(payload))
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response(result)


async def _validation_history(request: web.Request) -> web.Response:
    service = request.app[STATION_SERVICE_KEY]
    limit = _parse_limit(request, default=12)
    return web.json_response({"items": service.validation_history(limit=limit)})


async def _workbench_state(request: web.Request) -> web.Response:
    service = request.app[STATION_SERVICE_KEY]
    if request.method == "GET":
        payload = service.workbench_state()
        return web.json_response({"state": payload})

    payload = await request.json()
    try:
        saved = service.save_workbench_state(payload)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response({"state": saved})


async def _monitoring(request: web.Request) -> web.Response:
    service = request.app[STATION_SERVICE_KEY]
    manager = request.app[SESSION_MANAGER_KEY]
    session_snapshot = await manager.snapshot()
    session_id = session_snapshot.get("session_id") if isinstance(session_snapshot, dict) else None
    session_history_payload = await manager.session_history(limit=6)
    session_events_payload = await manager.events(limit=24, session_id=session_id)
    return web.json_response(
        service.monitoring_snapshot(
            session_snapshot=session_snapshot,
            session_history=session_history_payload.get("items", []),
            session_events=session_events_payload.get("items", []),
        )
    )


async def _execution(request: web.Request) -> web.Response:
    service = request.app[STATION_SERVICE_KEY]
    manager = request.app[SESSION_MANAGER_KEY]
    session_snapshot = await manager.snapshot()
    session_id = session_snapshot.get("session_id") if isinstance(session_snapshot, dict) else None
    session_history_payload = await manager.session_history(limit=6)
    session_events_payload = await manager.events(limit=24, session_id=session_id)
    return web.json_response(
        service.execution_snapshot(
            session_snapshot=session_snapshot,
            session_history=session_history_payload.get("items", []),
            session_events=session_events_payload.get("items", []),
        )
    )


async def _session_snapshot(request: web.Request) -> web.Response:
    manager = request.app[SESSION_MANAGER_KEY]
    return web.json_response(await manager.snapshot())


async def _session_events(request: web.Request) -> web.Response:
    manager = request.app[SESSION_MANAGER_KEY]
    limit = _parse_limit(request, default=40)
    session_id = request.query.get("session_id")
    return web.json_response(await manager.events(limit=limit, session_id=session_id))


async def _session_history(request: web.Request) -> web.Response:
    manager = request.app[SESSION_MANAGER_KEY]
    limit = _parse_limit(request, default=12)
    return web.json_response(await manager.session_history(limit=limit))


async def _session_start(request: web.Request) -> web.Response:
    manager = request.app[SESSION_MANAGER_KEY]
    payload = await request.json()
    try:
        result = await manager.start(SessionStartRequest.model_validate(payload))
    except (RuntimeError, ValueError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response(result)


async def _session_stop(request: web.Request) -> web.Response:
    manager = request.app[SESSION_MANAGER_KEY]
    return web.json_response(await manager.stop())


async def _kill_switch(request: web.Request) -> web.Response:
    manager = request.app[SESSION_MANAGER_KEY]
    payload = await request.json()
    if not isinstance(payload, dict):
        return web.json_response({"error": "payload must be a JSON object"}, status=400)
    reason = str(payload.get("reason", "station_manual_override"))
    # Bound the reason to avoid unbounded JSONL/telemetry growth.
    reason = reason[:256]
    try:
        result = await manager.trigger_kill_switch(reason)
    except RuntimeError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response(result)


async def _cleanup(app: web.Application) -> None:
    manager = app[SESSION_MANAGER_KEY]
    await manager.cleanup()


def create_app(
    *,
    service: StationService | None = None,
    session_manager: StationSessionManager | None = None,
) -> web.Application:
    """Create the QuantFlow Station application."""
    app = web.Application(middlewares=[_same_origin_guard])
    history_store = (
        getattr(service, "history_store", None)
        or getattr(session_manager, "_history_store", None)
        or StationHistoryStore()
    )
    app[STATION_SERVICE_KEY] = service or StationService(history_store=history_store)
    app[SESSION_MANAGER_KEY] = session_manager or StationSessionManager(history_store=history_store)
    app.router.add_get("/", _index)
    app.router.add_get("/api/overview", _overview)
    app.router.add_get("/api/strategies", _strategies)
    app.router.add_get("/api/data", _data_snapshot)
    app.router.add_post("/api/data/download", _data_download)
    app.router.add_post("/api/data/seed-demo", _data_seed_demo)
    app.router.add_post("/api/data/tag-source", _data_tag_source)
    app.router.add_post("/api/research", _research)
    app.router.add_get("/api/research/history", _research_history)
    app.router.add_post("/api/validate", _validate)
    app.router.add_get("/api/validate/history", _validation_history)
    app.router.add_get("/api/workbench/state", _workbench_state)
    app.router.add_post("/api/workbench/state", _workbench_state)
    app.router.add_get("/api/monitoring", _monitoring)
    app.router.add_get("/api/execution", _execution)
    app.router.add_get("/api/session", _session_snapshot)
    app.router.add_get("/api/session/events", _session_events)
    app.router.add_get("/api/session/history", _session_history)
    app.router.add_post("/api/session/start", _session_start)
    app.router.add_post("/api/session/stop", _session_stop)
    app.router.add_post("/api/session/kill-switch", _kill_switch)
    app.router.add_static("/static/", _static_dir())
    app.on_cleanup.append(_cleanup)
    return app


def run_station(host: str = "127.0.0.1", port: int = 8088) -> None:
    """Run the QuantFlow Station web server."""
    web.run_app(create_app(), host=host, port=port)
