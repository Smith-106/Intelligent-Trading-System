"""Redis cache for real-time market data.

.. deprecated:: 0.2.0
   This module is unused (zero instantiation across the entire codebase as of
   v0.1.3). It is retained for reference only and will be removed in v0.3.
   Do NOT import or instantiate RedisCache in new code. (M4-1.3)
"""

from __future__ import annotations

import json
import logging
import warnings
from typing import Any

import redis

from quantflow.common.exceptions import DataError

logger = logging.getLogger(__name__)

warnings.warn(
    "quantflow.data.redis_cache is deprecated and unused — "
    "it will be removed in v0.3. Do not import RedisCache.",
    DeprecationWarning,
    stacklevel=2,
)

TICKER_TTL = 60  # seconds


class RedisCache:
    """Cache layer for real-time market data."""

    def __init__(self, url: str = "redis://localhost:6379", db: int = 0) -> None:
        self._url = url
        self._db = db
        self._client: redis.Redis | None = None

    def connect(self) -> None:
        try:
            self._client = redis.from_url(self._url, db=self._db, decode_responses=True)
            self._client.ping()
            logger.info("Connected to Redis at %s", self._url)
        except Exception as e:
            logger.warning("Redis connection failed: %s. Caching disabled.", e)
            self._client = None

    def set_ticker(self, symbol: str, data: dict[str, Any]) -> None:
        if not self._client:
            return
        key = f"ticker:{symbol}"
        self._client.setex(key, TICKER_TTL, json.dumps(data))

    def get_ticker(self, symbol: str) -> dict[str, Any] | None:
        """Read a cached ticker.

        ISS-20260723-015 (GP1 fail-silent): previously returned ``None``
        both when the cache was not connected (``_client is None``) and on
        a genuine key miss — indistinguishable, so a caller treating
        ``None`` as "cache miss, fetch from source" would silently bypass
        the cache forever after a connection drop. Now raises ``DataError``
        when the client is not connected (a connection-state failure, not
        cache-miss); a real key miss still returns ``None``.
        """
        if not self._client:
            raise DataError(
                "RedisCache.get_ticker: client not connected — call connect() first "
                "(caching disabled by a prior connection failure is a failure, not a miss)"
            )
        key = f"ticker:{symbol}"
        raw = self._client.get(key)
        return json.loads(raw) if raw else None

    def set_latest_bar(self, symbol: str, timeframe: str, data: dict[str, Any]) -> None:
        if not self._client:
            return
        key = f"bar:{symbol}:{timeframe}"
        self._client.setex(key, 300, json.dumps(data))

    def get_latest_bar(self, symbol: str, timeframe: str) -> dict[str, Any] | None:
        """Read a cached latest bar.

        ISS-20260723-015 (GP1 fail-silent): see ``get_ticker`` — raises
        ``DataError`` when the client is not connected; key miss still
        returns ``None``.
        """
        if not self._client:
            raise DataError(
                "RedisCache.get_latest_bar: client not connected — call connect() first"
            )
        key = f"bar:{symbol}:{timeframe}"
        raw = self._client.get(key)
        return json.loads(raw) if raw else None

    def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
