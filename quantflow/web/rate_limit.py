"""Per-IP token-bucket rate limiting for the QuantFlow Station web app.

ISS-001 (SEC-006): /api/research and /api/validate run expensive backtest/
validation synchronously; /api/data/download triggers OKX fetches + parquet
writes. Without a per-client limit a local/network caller can starve the
trading event loop by flooding these endpoints. This middleware applies a
token bucket per client IP to mutation/compute endpoints.

Threat model (single operator, local-first): the limit is a guard against
accidental floods (a misbehaving client retrying in a tight loop) and a light
DoS brake if the Station is mistakenly bound to a network interface. It is NOT
a robust public-facing rate limiter — network exposure is governed by the
shared-secret token in ``security.py``. The bucket sizes are conservative on
purpose: an interactive operator will not hit them, but a tight retry loop or
a burst of automated requests will receive 429.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from aiohttp import web
from aiohttp.typedefs import Middleware

# Endpoints that do real work (backtest / validation / OKX fetch / live-trading
# control) and therefore must be rate-limited. Cheap GETs (overview, snapshot,
# history) are exempt — they read in-memory state and do not starve the loop.
_LIMITED_PATHS: frozenset[str] = frozenset(
    {
        "/api/data/download",
        "/api/data/seed-demo",
        "/api/data/tag-source",
        "/api/analysis/multi-tf",
        "/api/research",
        "/api/validate",
        "/api/session/start",
        "/api/session/stop",
        "/api/session/kill-switch",
        "/api/workbench/state",  # POST only; GETs are filtered by method below
    }
)

# Token bucket: capacity = burst size; refill = tokens per second.
_DEFAULT_CAPACITY = 10.0
_DEFAULT_REFILL_PER_SEC = 2.0


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


@dataclass
class RateLimiter:
    """Per-IP token bucket. Thread-safe via a single asyncio lock (the Station
    is single-loop; buckets are mutated only on the event loop)."""

    capacity: float = _DEFAULT_CAPACITY
    refill_per_sec: float = _DEFAULT_REFILL_PER_SEC
    _buckets: dict[str, _Bucket] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def _now(self) -> float:
        # time.monotonic is not affected by wall-clock changes and is safe to
        # use across the event loop. (Cannot use time.time for bucket math.)
        return time.monotonic()

    async def acquire(self, client_key: str) -> bool:
        """Try to consume one token for ``client_key``. Returns True if allowed."""
        async with self._lock:
            now = self._now()
            # REV-019-SEC RV5: lazy eviction — buckets for keys unseen for an
            # hour are dropped so rotated/spoofed keys cannot grow memory.
            stale_cutoff = now - 3600.0
            if len(self._buckets) > 64:
                dead = [k for k, b in self._buckets.items() if b.last_refill < stale_cutoff]
                for k in dead:
                    del self._buckets[k]
            bucket = self._buckets.get(client_key)
            if bucket is None:
                bucket = _Bucket(tokens=self.capacity, last_refill=now)
                self._buckets[client_key] = bucket
            else:
                elapsed = now - bucket.last_refill
                bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.refill_per_sec)
                bucket.last_refill = now
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True
            return False

    def retry_after(self, client_key: str) -> float:
        """Seconds until the next token is available for ``client_key``.

        Returns 0 when a token is already available, or a positive wait when
        the bucket is empty. A non-positive refill rate (no recovery) yields a
        1-second hint rather than dividing by zero — the caller will still be
        rate-limited on the next attempt, and the Retry-After header must be a
        finite integer.
        """
        bucket = self._buckets.get(client_key)
        if bucket is None or bucket.tokens >= 1.0:
            return 0.0
        if self.refill_per_sec <= 0.0:
            return 1.0
        deficit = 1.0 - bucket.tokens
        return max(0.0, deficit / self.refill_per_sec)


#: Comma/space-separated peer IPs allowed to set X-Forwarded-For on behalf of
#: clients (reverse-proxy deployments). Empty by default: without an explicit
#: proxy list the header is attacker-controlled and must not be trusted.
_TRUSTED_PROXIES = frozenset(
    ip.strip() for ip in os.environ.get("STATION_TRUSTED_PROXIES", "").replace(",", " ").split() if ip.strip()
)


def _client_key(request: web.Request) -> str:
    """Identify the calling client.

    SEC-RV19-001: X-Forwarded-For is honored ONLY when the direct transport
    peer is in STATION_TRUSTED_PROXIES. Unconditionally trusting the header
    let any client rotate fresh rate-limit buckets per request.
    """
    peername = request.transport.get_extra_info("peername") if request.transport else None
    peer_ip = str(peername[0]) if peername else "unknown"
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded and peer_ip in _TRUSTED_PROXIES:
        # First hop is the originating client, as recorded by our proxy.
        return forwarded.split(",")[0].strip()
    return peer_ip


def rate_limit_middleware(
    limiter: RateLimiter | None = None,
) -> Middleware:
    """Build an aiohttp middleware applying ``limiter`` to expensive endpoints.

    Only mutation/compute paths in :data:`_LIMITED_PATHS` are throttled; all
    other requests pass through untouched. On rejection returns 429 with a
    ``Retry-After`` header (seconds, rounded up).
    """
    state = limiter or RateLimiter()

    @web.middleware
    async def _middleware(
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        # SEC-RV19-008: normalize the trailing slash and match exactly —
        # frozenset membership has no prefix bypass, but "/download/" used to
        # slip past both route-adjacent normalization and this check.
        if request.path.rstrip("/") in _LIMITED_PATHS and request.method != "GET":
            key = _client_key(request)
            # SEC-RV19-004: with token auth configured, fold a digest of the
            # credential into the bucket key — per-credential limits instead
            # of one shared per-IP bucket (multi-tab self-DoS).
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                import hashlib

                key = f"{key}:{hashlib.sha256(auth.encode()).hexdigest()[:16]}"
            allowed = await state.acquire(key)
            if not allowed:
                retry = state.retry_after(key)
                return web.json_response(
                    {"error": "rate limit exceeded; retry later"},
                    status=429,
                    headers={"Retry-After": str(max(1, int(retry) + 1))},
                )
        return await handler(request)

    return _middleware
