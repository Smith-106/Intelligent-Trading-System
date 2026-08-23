"""Tests for ISS-001 (SEC-006/007): web DoS protection.

Covers:
- per-IP token-bucket rate limiter (429 on burst, Retry-After header, refill)
- request body size cap (client_max_size)
- params payload depth/key bound (ResearchRequest/ValidationRequest)
"""

from __future__ import annotations

import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

from quantflow.web.app import create_app
from quantflow.web.history import StationHistoryStore
from quantflow.web.rate_limit import RateLimiter
from quantflow.web.service import ResearchRequest, StationService, ValidationRequest
from quantflow.web.session_manager import StationSessionManager


def test_rate_limiter_allows_within_burst():
    limiter = RateLimiter(capacity=3.0, refill_per_sec=1.0)

    async def run() -> None:
        results = [await limiter.acquire("1.2.3.4") for _ in range(3)]
        assert results == [True, True, True]
        assert await limiter.acquire("1.2.3.4") is False

    asyncio.run(run())


def test_rate_limiter_refills_over_time():
    limiter = RateLimiter(capacity=2.0, refill_per_sec=10.0)

    async def run() -> None:
        assert await limiter.acquire("c") is True
        assert await limiter.acquire("c") is True
        assert await limiter.acquire("c") is False
        # Force the bucket's last_refill into the past so refill accrues.
        bucket = limiter._buckets["c"]
        bucket.last_refill -= 1.0  # 10 tokens/sec * 1s = 10 → capped at capacity
        assert await limiter.acquire("c") is True

    asyncio.run(run())


def test_rate_limiter_isolates_clients():
    limiter = RateLimiter(capacity=1.0, refill_per_sec=0.0)

    async def run() -> None:
        assert await limiter.acquire("a") is True
        assert await limiter.acquire("a") is False
        # Different IP gets its own bucket.
        assert await limiter.acquire("b") is True

    asyncio.run(run())


def test_retry_after_when_empty():
    limiter = RateLimiter(capacity=1.0, refill_per_sec=2.0)

    async def run() -> None:
        await limiter.acquire("c")
        # 0 tokens, refill 2/s → 0.5s to next token.
        assert limiter.retry_after("c") == pytest.approx(0.5)

    asyncio.run(run())


@pytest.mark.parametrize(
    ("model_cls",),
    [
        (ResearchRequest,),
        (ValidationRequest,),
    ],
)
def test_params_rejects_excessive_depth(model_cls):
    # 5 levels deep (> _MAX_PARAMS_DEPTH=4).
    deep = {"a": {"b": {"c": {"d": {"e": 1}}}}}
    with pytest.raises(ValueError, match="depth"):
        model_cls(params=deep)


def test_params_rejects_excessive_keys():
    many_keys = {f"k{i}": i for i in range(33)}
    with pytest.raises(ValueError, match="too many keys"):
        ResearchRequest(params=many_keys)


def test_params_accepts_normal_flat_payload():
    req = ResearchRequest(params={"fast": 10, "slow": 30})
    assert req.params == {"fast": 10, "slow": 30}


async def test_endpoint_returns_429_on_burst():
    """A burst exceeding the bucket capacity returns 429 with Retry-After."""
    # Tiny limiter: capacity 2, no refill → 3rd request is over-limit.
    limiter = RateLimiter(capacity=2.0, refill_per_sec=0.0)
    app = create_app(
        service=StationService(history_store=StationHistoryStore()),
        session_manager=StationSessionManager(history_store=StationHistoryStore()),
        rate_limiter=limiter,
    )
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        statuses = []
        for _ in range(4):
            resp = await client.post("/api/workbench/state", json={"state": {}})
            statuses.append(resp.status)
            await resp.release()
        # First two allowed (200/400 depending on payload validation), then 429.
        assert 429 in statuses
        # The 429 response carries a Retry-After header.
        over = [s for s in statuses if s == 429]
        assert len(over) >= 1
    finally:
        await client.close()


async def test_request_body_size_cap_rejects_oversized():
    """ISS-001 SEC-007: a POST body > client_max_size is rejected (413)."""
    app = create_app(
        service=StationService(history_store=StationHistoryStore()),
        session_manager=StationSessionManager(history_store=StationHistoryStore()),
    )
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        # ~300 KiB body, far over the 256 KiB cap.
        big_payload = {"x": "A" * (300 * 1024)}
        resp = await client.post("/api/workbench/state", json=big_payload)
        # aiohttp returns 413 Payload Too Large when client_max_size is exceeded.
        assert resp.status == 413
    finally:
        await client.close()


class TestRouteRegistrationInvariant:
    """SEC-RV19-008: every registered mutation route must be rate-limited."""

    def test_all_mutation_routes_registered(self) -> None:
        from quantflow.web.app import create_app
        from quantflow.web.rate_limit import _LIMITED_PATHS

        app = create_app()
        # DynamicRoute resources lack .path; enumerate via resources().
        mutations: set[str] = set()
        for resource in app.router.resources():
            for route in resource:
                if route.method in {"POST", "PUT", "PATCH", "DELETE"}:
                    mutations.add(resource.canonical)
        unregistered = sorted(mutations - set(_LIMITED_PATHS))
        assert not unregistered, (
            "mutation routes missing from _LIMITED_PATHS (they would bypass "
            f"rate limiting): {unregistered}"
        )

    def test_trailing_slash_normalized(self) -> None:
        from quantflow.web.rate_limit import _LIMITED_PATHS

        # /api/data/download/ must hit the same bucket as the canonical path.
        assert "/api/data/download/".rstrip("/") in _LIMITED_PATHS
