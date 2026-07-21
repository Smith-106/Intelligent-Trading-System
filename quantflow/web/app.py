"""Aiohttp application for QuantFlow Station."""

from __future__ import annotations

import logging
from importlib import resources
from pathlib import Path

from aiohttp import web

from quantflow.common.exceptions import DataError, GatewayConnectionError
from quantflow.common.redaction import redact_secrets
from quantflow.web.history import StationHistoryStore
from quantflow.web.rate_limit import RateLimiter, rate_limit_middleware
from quantflow.web.security import (
    STATION_TOKEN_ENV,
    _is_loopback_host,
    _station_token,
)
from quantflow.web.security import (
    same_origin_guard as _same_origin_guard,
)
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

# ISS-001 (SEC-007): cap request body size. aiohttp defaults to 1 MiB, which is
# far more than any legitimate Station request needs (research/validate params
# are a small dict; the largest payload is workbench state at ~64 KiB). A 256
# KiB ceiling rejects oversized bodies that could be used to starve memory or
# bury a deeply-nested params payload.
MAX_REQUEST_BODY_BYTES = 256 * 1024

logger = logging.getLogger(__name__)

# Auth/CSRF policy now lives in quantflow.web.security (REV-013) so it can be
# audited and tested in isolation and reused by any Station entry point. The
# names below are re-exported for back-compat (tests import the underscored
# forms from this module); the authoritative definitions are in security.py.


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


def _error_response(exc: BaseException, *, status: int = 400) -> web.Response:
    """Build a client-safe 400 response from a service-layer exception.

    ISS-004/ISS-002: service ``ValueError`` echoes user-supplied config paths;
    ``DataError``/``GatewayConnectionError`` may embed internal paths, OKX error
    bodies, or DuckDB text. Redact at this single sink so no secret-shaped
    value (OKX creds, alert tokens, redis URLs) reaches the client. The full
    exception is logged server-side for diagnostics.
    """
    message = redact_secrets(str(exc))
    logger.warning("Station handler error: %s: %s", type(exc).__name__, message)
    return web.json_response({"error": message}, status=status)


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
        return _error_response(exc)
    return web.json_response(result)


async def _data_seed_demo(request: web.Request) -> web.Response:
    service = request.app[STATION_SERVICE_KEY]
    payload = await request.json()
    try:
        result = service.seed_demo_data(DataDownloadRequest.model_validate(payload))
    except ValueError as exc:
        return _error_response(exc)
    return web.json_response(result)


async def _data_tag_source(request: web.Request) -> web.Response:
    service = request.app[STATION_SERVICE_KEY]
    payload = await request.json()
    try:
        result = service.tag_data_source(DataSourceTagRequest.model_validate(payload))
    except ValueError as exc:
        return _error_response(exc)
    return web.json_response(result)


async def _research(request: web.Request) -> web.Response:
    service = request.app[STATION_SERVICE_KEY]
    payload = await request.json()
    try:
        result = service.research(ResearchRequest.model_validate(payload))
    except ValueError as exc:
        return _error_response(exc)
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
        return _error_response(exc)
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
        return _error_response(exc)
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
        return _error_response(exc)
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
        return _error_response(exc)
    return web.json_response(result)


async def _cleanup(app: web.Application) -> None:
    manager = app[SESSION_MANAGER_KEY]
    await manager.cleanup()


def create_app(
    *,
    service: StationService | None = None,
    session_manager: StationSessionManager | None = None,
    history_store: StationHistoryStore | None = None,
    rate_limiter: RateLimiter | None = None,
) -> web.Application:
    """Create the QuantFlow Station application.

    SECURITY note (REV-006): this constructor is host-agnostic by design so it
    can be exercised in tests without binding a socket. The non-loopback bind
    guard therefore lives at the bind boundary in :func:`run_station` (the only
    entry point that knows the host) — it cannot be checked here because
    ``host`` is not a parameter. Tests construct the app directly and assume a
    loopback/loopback-equivalent threat model; the guard is enforced when the
    server is actually launched.

    ``rate_limiter`` is injectable so tests can drive a tiny bucket to assert
    429 behavior without flooding the production-sized limiter.
    """
    # ISS-001 (SEC-006/007): rate-limit mutation/compute endpoints (per-IP token
    # bucket) and cap request body size, so a flood of /api/research or
    # /api/data/download requests cannot starve the trading event loop or be
    # used as a memory-amplification vector. Order matters: rate_limit runs
    # before same_origin_guard so an over-limit client is rejected cheapest.
    app = web.Application(
        middlewares=[rate_limit_middleware(rate_limiter), _same_origin_guard],
        client_max_size=MAX_REQUEST_BODY_BYTES,
    )
    # REV-012: history_store is now an explicit parameter rather than reached
    # out of session_manager._history_store (a private attribute). The private
    # getattr fallback is gone; callers pass history_store explicitly, and the
    # service/session_manager both expose it as a public field/param.
    resolved_store = history_store or StationHistoryStore()
    app[STATION_SERVICE_KEY] = service or StationService(history_store=resolved_store)
    app[SESSION_MANAGER_KEY] = session_manager or StationSessionManager(
        history_store=resolved_store
    )
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
