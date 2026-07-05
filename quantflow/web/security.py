"""Auth + CSRF policy for the QuantFlow Station web app.

Centralizes the security controls that gate mutation endpoints (the live-
trading controls) so they can be audited and unit-tested in isolation, and
reused by any future Station entry point — not buried inside the routing
module (REV-013).

Threat model (single operator, local-first):
- Network exposure is governed by a shared-secret Bearer token
  (``QUANTFLOW_STATION_TOKEN``). Binding to a non-loopback host without a
  token is refused at launch (see ``app.run_station``).
- Browser-driven CSRF is governed by the Origin header: a cross-site POST
  sends an Origin that will not match Host, and browsers cannot forge Host.
- Non-browser clients (curl, the TestClient) omit Origin; such clients
  already have local access, so absent Origin is allowed.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Awaitable, Callable
from ipaddress import ip_address
from urllib.parse import urlparse

from aiohttp import web

# Local-only station: mutation endpoints must come from the same origin to
# prevent browser-driven CSRF (a random web page posting to
# /api/session/kill-switch on localhost). Read-only GETs are exempt.
_MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Shared-secret token guarding mutation endpoints. Read per-request from the
# env (not cached at module import) so token rotation takes effect without a
# process restart. If unset, the station runs token-less (only safe on loopback).
STATION_TOKEN_ENV = "QUANTFLOW_STATION_TOKEN"


def _station_token() -> str | None:
    """The shared secret required for mutation endpoints, if configured.

    Read from QUANTFLOW_STATION_TOKEN on each mutation request (per-request,
    not cached) so rotating the token — e.g. after a suspected leak — takes
    effect without restarting the Station. When unset, the station allows
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


@web.middleware
async def same_origin_guard(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Reject unauthenticated / cross-origin mutations to trading controls.

    Two layered controls (defends SEC-002 no-auth and SEC-004 Origin-bypass),
    BOTH applied to every mutation (POST/PUT/PATCH/DELETE):

    1. Shared-secret auth: if QUANTFLOW_STATION_TOKEN is set, every mutation
       requires ``Authorization: Bearer <token>`` (constant-time
       ``hmac.compare_digest``). A valid token does NOT skip CSRF — the
       controls are orthogonal (auth = who, CSRF = browser intent).

    2. CSRF: a browser-driven cross-site POST sends an ``Origin`` header
       that will not match the local ``Host`` (browsers cannot forge Host).
       When ``Origin`` is present and mismatches ``Host`` → 403. When
       ``Origin`` is absent (non-browser clients like the TestClient or
       curl) → allowed: such clients already have local access in the
       single-operator threat model, and the token control (1) governs
       network exposure.

       Note on ``X-Requested-With``: a previous version accepted the mere
       presence of this header as an alternative same-origin signal. That
       was a CSRF bypass — ``X-Requested-With`` is NOT a forbidden CORS
       header, so any cross-origin fetch can set it. It is no longer
       consulted. (Origin is browser-controlled and cannot be forged, so
       it is the trustworthy signal.)

       The Host header alone is NOT trusted as the reference address because
       a non-browser client can forge it — we rely on it only as the address
       a browser guarantees matches the actual server.
    """
    if request.method in _MUTATION_METHODS:
        # 1. Shared-secret auth (when configured). Does NOT short-circuit
        #    CSRF — both controls run (auth=who, CSRF=browser intent).
        token = _station_token()
        if token:
            auth = request.headers.get("Authorization", "")
            expected = f"Bearer {token}"
            # Constant-time comparison to avoid token leakage via timing.
            if not auth or not hmac.compare_digest(auth, expected):
                return web.json_response({"error": "unauthorized"}, status=401)

        # 2. CSRF: reject when Origin is present and does not match Host.
        #    Origin absent (non-browser) is allowed — token governs network.
        origin = request.headers.get("Origin")
        if origin:
            host = request.headers.get("Host", "")
            try:
                origin_host = urlparse(origin).netloc
            except ValueError:
                origin_host = ""
            same_origin = bool(origin_host) and bool(host) and origin_host == host
            if not same_origin:
                return web.json_response(
                    {"error": "cross-origin mutations are not permitted"},
                    status=403,
                )
    return await handler(request)
