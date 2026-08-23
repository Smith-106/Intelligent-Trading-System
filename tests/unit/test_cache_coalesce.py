"""REV-021/025: TTLCache miss-coalescing behavior.

Covers:
- N concurrent misses on the same key -> exactly one compute call
- compute runs OUTSIDE the store lock: plain get() proceeds during a scan
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from quantflow.web.cache import TTLCache


def test_concurrent_misses_compute_once() -> None:
    cache = TTLCache(ttl_seconds=5.0)
    calls: list[int] = []
    gate = threading.Event()

    def slow_compute() -> dict[str, int]:
        calls.append(1)
        gate.wait(timeout=5)  # hold "scan" open until all workers arrived
        return {"v": len(calls)}

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(cache.get_or_set, "k", slow_compute) for _ in range(4)]
        time.sleep(0.2)  # let all four workers reach the compute lock
        gate.set()
        results = [f.result(timeout=5) for f in futures]

    assert len(calls) == 1, f"expected single compute, got {len(calls)}"
    assert all(r == results[0] for r in results)


def test_get_not_blocked_during_compute() -> None:
    """REV-025: the ~1s scan must not starve plain readers."""
    cache = TTLCache(ttl_seconds=5.0)
    release = threading.Event()
    started = threading.Event()

    def scan() -> str:
        started.set()
        release.wait(timeout=5)
        return "value"

    import concurrent.futures

    with ThreadPoolExecutor(max_workers=2) as ex:
        compute_future = ex.submit(cache.get_or_set, "k", scan)
        assert started.wait(timeout=5), "compute never started"
        # Plain read while the scan is mid-flight: must return promptly.
        t0 = time.monotonic()
        assert cache.get("k") is None
        elapsed = time.monotonic() - t0
        release.set()
        assert compute_future.result(timeout=5) == "value"

    assert elapsed < 1.0, f"get() blocked {elapsed:.2f}s behind the compute lock"
