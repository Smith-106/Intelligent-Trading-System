"""Aiohttp application for QuantFlow Station."""

from __future__ import annotations

import hmac
import os
from collections.abc import Awaitable, Callable
from importlib import resources
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlparse

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
SESSION_MANAGER_KEY = web.AppKey("station_session_manager", StationSessionManager)

# Local-only station: mutation endpoints must come from the same origin to
# prevent browser-driven CSRF (a random web page posting to
# /api/session/kill-switch on localhost). Read-only GETs are exempt.
_MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Shared-secret token guarding mutation endpoints. Read once from the env at
# module import; if unset, the station runs token-less (only safe on loopback).
STATION_TOKEN_ENV = "QUANTFLOW_STATION_TOKEN"


def _station_token() -> str | None:
    """The shared secret required for mutation endpoints, if configured.

    Read from QUANTFLOW_STATION_TOKEN. When unset, the station allows
    unauthenticated mutations ONLY on loopback binds (the default single-
    operator mode). Binding to a non-loopback host without a token is refused
    in run_station to prevent silently exposing live-trading controls.
    """
    token = os.environ.get(STATION_TOKEN_ENV, "").strip()
    return token or None


def _is_loopback_host(host: str) -> bool:
    """True if ``host`` resolves to a loopback address (127.0.0.0/8 or ::1)."""
    if not host:
        return False
    # Host may be "0.0.0.0", "127.0.0.1", "localhost", or "[::1]".
    cleaned = host.strip().strip("[]")
    if cleaned == "localhost":
        return True
    if cleaned in ("0.0.0.0", "::"):
        # 0.0.0.0 / :: bind to all interfaces — NOT loopback-only exposure.
        return False
    try:
        return ip_address(cleaned).is_loopback
    except ValueError:
        return False


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
async def _same_origin_guard(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Reject unauthenticated / cross-origin mutations to trading controls.

    Two layered controls (defends SEC-002 no-auth and SEC-004 Origin-bypass):

    1. Shared-secret auth: if QUANTFLOW_STATION_TOKEN is set, every mutation
       requires ``Authorization: Bearer <token>``. Without the token, any
       local process could start a live session or flip the kill switch.

    2. CSRF: a browser-driven cross-site POST sends an ``Origin`` header that
       will not match the local ``Host`` (127.0.0.1:<port>) — browsers do not
       let pages override the Host header, so the comparison is trustworthy for
       browser-originated requests. When ``Origin`` is absent (non-browser
       clients like the TestClient or curl), the request is allowed: such
       clients already have local access in the single-operator threat model,
       and the token control (1) governs network exposure. The Station UI also
       sends ``X-Requested-With`` as defense in depth; its presence is an
       alternative same-origin signal.

       Note: the Host header alone is NOT trusted for the comparison because a
       non-browser client can forge it — we only rely on it as the reference
       address that a browser guarantees matches the actual server.
    """
    if request.method in _MUTATION_METHODS:
        # 1. Shared-secret auth (when configured).
        token = _station_token()
        if token:
            auth = request.headers.get("Authorization", "")
            expected = f"Bearer {token}"
            # Constant-time comparison to avoid token leakage via timing.
            if not auth or not hmac.compare_digest(auth, expected):
                return web.json_response({"error": "unauthorized"}, status=401)
            return await handler(request)

        # 2. CSRF: reject when Origin is present and does not match Host.
        origin = request.headers.get("Origin")
        if origin:
            host = request.headers.get("Host", "")
            try:
                origin_host = urlparse(origin).netloc
            except Exception:
                origin_host = ""
            same_origin = bool(origin_host) and bool(host) and origin_host == host
            has_custom_header = request.headers.get("X-Requested-With") is not None
            if not same_origin and not has_custom_header:
                return web.json_response(
                    {"error": "cross-origin mutations are not permitted"},
                    status=403,
                )
    return await handler(request)


def _static_dir() -> Path:
    return Path(str(resources.files(STATIC_PACKAGE)))


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
    """Run the QuantFlow Station web server.

    SECURITY: if ``host`` is not loopback, a shared-secret token
    (QUANTFLOW_STATION_TOKEN) MUST be set — otherwise the 23 endpoints
    (including live-trading controls) would be exposed to the network with no
    authentication. Refuses to start in that case rather than silently
    exposing live-trading controls.
    """
    if not _is_loopback_host(host) and not _station_token():
        raise RuntimeError(
            f"Refusing to bind Station to non-loopback host {host!r} without "
            f"an auth token. Set the {STATION_TOKEN_ENV} environment variable "
            "to a strong secret before exposing the Station on the network."
        )
    web.run_app(create_app(), host=host, port=port)
