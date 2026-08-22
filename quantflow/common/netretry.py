"""Shared network-retry primitives for exchange meta fetchers (REV-009/S2).

Extracted from ``data/market_meta_fetcher`` per ISS-REV007-05: bybit_meta_fetcher
borrowed the underscore-private ``_is_retryable`` / ``_to_float``, making a
private implementation the de-facto cross-module contract. The public home is
here; the old private names remain importable from their origin module as
aliases so existing tests and callers keep working.

Import-light by design: only stdlib + ccxt, no pandas.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable
from typing import Any

import ccxt

__all__ = [
    "BASE_BACKOFF_S",
    "CALL_TIMEOUT",
    "MAX_RETRIES",
    "MIN_ENDPOINT_INTERVAL_S",
    "RATE_LIMIT_ERROR_CODE",
    "RetryableLimiter",
    "is_retryable_error",
    "retry_call",
    "to_float",
    "to_int",
]

MIN_ENDPOINT_INTERVAL_S = 0.2
MAX_RETRIES = 3
BASE_BACKOFF_S = 1.0
#: Per-call network timeout (mirrors DataFetcher.CALL_TIMEOUT).
CALL_TIMEOUT = 30.0
RATE_LIMIT_ERROR_CODE = "50011"


class RetryableLimiter:
    """IP-level serial rate limiter (analyze locked decision: self-throttle).

    Guarantees at least ``min_interval`` seconds between the START of
    consecutive requests, independent of ccxt's internal throttling. One
    limiter instance is shared across all meta endpoints of a session.

    Formerly ``market_meta_fetcher.RateLimiter``; the old name remains as an
    alias there.
    """

    def __init__(self, min_interval: float = MIN_ENDPOINT_INTERVAL_S) -> None:
        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last_request = 0.0  # monotonic timestamp of last granted slot

    @property
    def min_interval(self) -> float:
        return self._min_interval

    async def acquire(self) -> None:
        """Wait until the next request slot is available, then claim it."""
        async with self._lock:
            wait = self._last_request + self._min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()


async def retry_call(
    limiter: RetryableLimiter,
    factory: Callable[[], Awaitable[Any]],
    op: str,
    *,
    logger_: logging.Logger | None = None,
) -> Any:
    """Run one endpoint call under ``limiter`` with bounded exponential retry.

    IMP-REV013-4: single implementation replacing the two drifting copies
    (MarketMetaFetcher._retry_call method + bybit_meta_fetcher module
    function). Retryable failures back off BASE_BACKOFF_S -> x2 (capped at
    4s) with jitter; non-retryable errors raise DataError immediately;
    exhaustion raises DataError (fail-closed).
    """
    import asyncio
    import random

    from quantflow.common.exceptions import DataError

    delay = BASE_BACKOFF_S
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            await limiter.acquire()
            return await asyncio.wait_for(factory(), timeout=CALL_TIMEOUT)
        except Exception as e:
            if not is_retryable_error(e):
                raise DataError(f"{op} failed: {e}") from e
            last_exc = e
            if attempt >= MAX_RETRIES:
                break
            jitter = random.uniform(0.0, 0.1 * delay)
            if logger_ is not None:
                logger_.warning(
                    "%s retryable failure (%s); backoff %.2fs (attempt %d/%d)",
                    op, e, delay + jitter, attempt + 1, MAX_RETRIES,
                )
            await asyncio.sleep(delay + jitter)
            delay *= 2
    raise DataError(f"{op} failed after {MAX_RETRIES} retries: {last_exc}") from last_exc


def to_float(value: Any, default: float = 0.0) -> float:
    """Coerce an exchange payload field to a finite float (fail to default)."""
    if value is None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def to_int(value: Any, default: int = 0) -> int:
    """Coerce an exchange payload field to int milliseconds."""
    if value is None:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def is_retryable_error(exc: Exception) -> bool:
    """True for OKX 50011 rate-limit responses and network-class errors."""
    if RATE_LIMIT_ERROR_CODE in str(exc):
        return True
    if isinstance(exc, (asyncio.TimeoutError, ConnectionError, OSError)):
        return True
    return isinstance(exc, (ccxt.RateLimitExceeded, ccxt.DDoSProtection, ccxt.NetworkError))
