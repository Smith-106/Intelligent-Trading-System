"""Redis cache for real-time market data."""

from __future__ import annotations

import json
import logging
from typing import Any

import redis

logger = logging.getLogger(__name__)

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
        if not self._client:
            return None
        key = f"ticker:{symbol}"
        raw = self._client.get(key)
        return json.loads(raw) if raw else None

    def set_latest_bar(self, symbol: str, timeframe: str, data: dict[str, Any]) -> None:
        if not self._client:
            return
        key = f"bar:{symbol}:{timeframe}"
        self._client.setex(key, 300, json.dumps(data))

    def get_latest_bar(self, symbol: str, timeframe: str) -> dict[str, Any] | None:
        if not self._client:
            return None
        key = f"bar:{symbol}:{timeframe}"
        raw = self._client.get(key)
        return json.loads(raw) if raw else None

    def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
