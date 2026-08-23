"""Process-level TTL cache for expensive snapshot reads (PERF-REV015).

The perf_api audit found `overview()` performs a full-history parquet scan
per call and is invoked by data_snapshot, monitoring_snapshot AND
execution_snapshot — i.e. one frontend poll cycle triggers 2-3 identical
scans. A tiny in-process TTL dict removes the duplication without adding a
dependency (redis_cache.py is deprecated/unused; do not resurrect it).

Station runs as a single aiohttp process, so process-level caching is
sufficient; revisit only for multi-worker deployments.
"""

from __future__ import annotations

import threading
import time
from typing import Any

__all__ = ["OVERVIEW_TTL_S", "TTLCache"]


class TTLCache:
    """Minimal thread-safe TTL cache (single-value keys, monotonic clock)."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is not None and now - entry[0] < self._ttl:
                self.hits += 1
                return entry[1]
            if entry is not None:
                del self._store[key]
            self.misses += 1
            return None

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (time.monotonic(), value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


#: Below the fastest frontend poll cadence; collapses the data/monitoring/
#: execution triple-scan of overview() into one parquet read per cycle.
OVERVIEW_TTL_S = 4.0
