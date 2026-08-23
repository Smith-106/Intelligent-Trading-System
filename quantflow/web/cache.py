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
from collections.abc import Callable
from typing import Any

__all__ = ["OVERVIEW_TTL_S", "TTLCache"]


class TTLCache:
    """Minimal thread-safe TTL cache (single-value keys, monotonic clock)."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        # REV-025: separate miss-coalescing lock — compute() runs OUTSIDE
        # _lock so the ~1s parquet scan never blocks plain get()/set().
        self._compute_lock = threading.Lock()
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

    def get_or_set(self, key: str, compute: Callable[[], Any]) -> Any:
        """Read-through with miss coalescing (REV-021-PERF, REV-025 fix).

        Exactly ONE caller recomputes per expired key: the rest wait on
        _compute_lock and then find the fresh entry. The scan itself runs
        OUTSIDE _lock — only concurrent misses serialize with each other,
        never with plain reads/writes (REV-025: holding _lock across the
        ~0.9s scan starved get()/set()/clear()).
        """
        hit = self.get(key)
        if hit is not None:
            return hit
        with self._compute_lock:
            # Double-check: an earlier waiter may have filled it already.
            hit = self.get(key)
            if hit is not None:
                return hit
            value = compute()
            self.set(key, value)
            return value


#: Below the fastest frontend poll cadence; collapses the data/monitoring/
#: execution triple-scan of overview() into one parquet read per cycle.
OVERVIEW_TTL_S = 4.0

