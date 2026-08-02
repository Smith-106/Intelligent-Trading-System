"""Unit tests for DataQualityMonitor Redis fallback (ISS-20260802-010).

Tests cover:
- InMemoryStateStore basic operations
- Graceful degradation when Redis unavailable
- DQ Monitor operates correctly without Redis
- Degraded mode flag and logging
- State consistency within process
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from quantflow.data.dq_monitor import DataQualityMonitor, InMemoryStateStore


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@dataclass
class MockBar:
    """Mock bar for testing."""
    symbol: str = "BTC/USDT"
    timestamp: float = 0.0
    open: float = 50000.0
    high: float = 50100.0
    low: float = 49900.0
    close: float = 50050.0
    volume: float = 100.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


class FailingRedis:
    """Redis mock that always raises ConnectionError."""

    async def get(self, key: str):
        raise ConnectionError("Redis connection refused")

    async def set(self, key: str, value):
        raise ConnectionError("Redis connection refused")


class WorkingRedis:
    """Redis mock that works correctly."""

    def __init__(self):
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value) -> None:
        self._store[key] = str(value)


# ---------------------------------------------------------------------------
# Test: InMemoryStateStore
# ---------------------------------------------------------------------------


class TestInMemoryStateStore:
    """Tests for the in-memory fallback store."""

    @pytest.mark.asyncio
    async def test_get_set_basic(self):
        """Basic get/set operations work."""
        store = InMemoryStateStore()

        assert await store.get("key1") is None
        await store.set("key1", "value1")
        assert await store.get("key1") == "value1"

    @pytest.mark.asyncio
    async def test_overwrite(self):
        """Setting same key overwrites previous value."""
        store = InMemoryStateStore()

        await store.set("key", "old")
        await store.set("key", "new")
        assert await store.get("key") == "new"

    @pytest.mark.asyncio
    async def test_numeric_values_stored_as_string(self):
        """Numeric values are stored as strings."""
        store = InMemoryStateStore()

        await store.set("price", 50000.5)
        result = await store.get("price")
        assert result == "50000.5"
        assert float(result) == 50000.5

    @pytest.mark.asyncio
    async def test_clear(self):
        """Clear removes all keys."""
        store = InMemoryStateStore()

        await store.set("a", "1")
        await store.set("b", "2")
        assert store.key_count == 2

        store.clear()
        assert store.key_count == 0
        assert await store.get("a") is None


# ---------------------------------------------------------------------------
# Test: DQ Monitor without Redis (pure fallback mode)
# ---------------------------------------------------------------------------


class TestDQMonitorNoRedis:
    """Tests for DQ Monitor operating entirely without Redis."""

    @pytest.mark.asyncio
    async def test_initializes_without_redis(self):
        """DQ Monitor can be created with redis_cache=None and uses fallback directly."""
        monitor = DataQualityMonitor(
            redis_cache=None,
            enable_prometheus=False,
            use_in_memory_fallback=True,
        )
        # redis_cache=None means _redis_available=False, so it uses fallback
        # directly without entering "degraded" mode (degraded is for Redis→fallback transition)
        assert monitor._redis_available is False
        assert monitor._fallback_store is not None

    @pytest.mark.asyncio
    async def test_validate_bar_works_without_redis(self):
        """Bar validation succeeds using in-memory state."""
        monitor = DataQualityMonitor(
            redis_cache=None,
            enable_prometheus=False,
            use_in_memory_fallback=True,
        )

        bar = MockBar(symbol="BTC/USDT", close=50000.0, volume=100.0)
        result = await monitor.validate_bar(bar)

        assert result.valid is True
        assert result.score.overall_score >= 0.7
        assert len(result.violations) == 0

    @pytest.mark.asyncio
    async def test_freshness_tracking_in_memory(self):
        """Consecutive bars track freshness correctly in memory."""
        monitor = DataQualityMonitor(
            redis_cache=None,
            enable_prometheus=False,
            use_in_memory_fallback=True,
        )

        now = time.time()
        bar1 = MockBar(symbol="BTC/USDT", timestamp=now, close=50000.0)
        bar2 = MockBar(symbol="BTC/USDT", timestamp=now + 30, close=50100.0)

        result1 = await monitor.validate_bar(bar1)
        result2 = await monitor.validate_bar(bar2)

        # Both should be valid (30s staleness < 60s threshold)
        assert result1.valid is True
        assert result2.valid is True
        assert result2.score.freshness_score > 0.0

    @pytest.mark.asyncio
    async def test_price_spike_detected_in_memory(self):
        """Price spike detection works with in-memory state."""
        monitor = DataQualityMonitor(
            redis_cache=None,
            enable_prometheus=False,
            use_in_memory_fallback=True,
        )

        now = time.time()
        bar1 = MockBar(symbol="BTC/USDT", timestamp=now, close=50000.0)
        # 20% spike (well above 5% threshold)
        bar2 = MockBar(symbol="BTC/USDT", timestamp=now + 5, close=60000.0)

        await monitor.validate_bar(bar1)
        result2 = await monitor.validate_bar(bar2)

        # Should detect price spike
        assert result2.score.continuity_score < 0.5
        spike_violations = [v for v in result2.violations if v["type"] == "price_spike_anomaly"]
        assert len(spike_violations) == 1

    @pytest.mark.asyncio
    async def test_quality_report_without_redis(self):
        """Quality report works when initialized without Redis."""
        monitor = DataQualityMonitor(
            redis_cache=None,
            enable_prometheus=False,
            use_in_memory_fallback=True,
        )

        bar = MockBar(symbol="ETH/USDT", close=3000.0, volume=500.0)
        await monitor.validate_bar(bar)

        report = await monitor.get_quality_report("ETH/USDT")
        assert report["symbol"] == "ETH/USDT"
        assert report["last_close_price"] is not None
        # degraded_mode is False because no Redis was ever configured
        assert report["degraded_mode"] is False


# ---------------------------------------------------------------------------
# Test: Graceful Degradation (Redis → Fallback)
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """Tests for transition from Redis to in-memory fallback."""

    @pytest.mark.asyncio
    async def test_redis_failure_triggers_degraded_mode(self):
        """When Redis fails, monitor switches to degraded mode."""
        failing_redis = FailingRedis()
        monitor = DataQualityMonitor(
            redis_cache=failing_redis,
            enable_prometheus=False,
            use_in_memory_fallback=True,
        )

        # Initially not degraded (Redis configured)
        assert monitor.is_degraded is False

        bar = MockBar(symbol="BTC/USDT", close=50000.0)
        result = await monitor.validate_bar(bar)

        # After Redis failure, should be in degraded mode
        assert monitor.is_degraded is True
        # But validation should still succeed via fallback
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_degraded_mode_persists(self):
        """Once degraded, monitor stays degraded (no flapping)."""
        failing_redis = FailingRedis()
        monitor = DataQualityMonitor(
            redis_cache=failing_redis,
            enable_prometheus=False,
            use_in_memory_fallback=True,
        )

        bar1 = MockBar(symbol="BTC/USDT", timestamp=time.time(), close=50000.0)
        await monitor.validate_bar(bar1)
        assert monitor.is_degraded is True

        # Second bar should still work in degraded mode
        bar2 = MockBar(symbol="BTC/USDT", timestamp=time.time() + 10, close=50100.0)
        result2 = await monitor.validate_bar(bar2)
        assert result2.valid is True
        assert monitor.is_degraded is True

    @pytest.mark.asyncio
    async def test_working_redis_no_degradation(self):
        """With working Redis, monitor never enters degraded mode."""
        working_redis = WorkingRedis()
        monitor = DataQualityMonitor(
            redis_cache=working_redis,
            enable_prometheus=False,
            use_in_memory_fallback=True,
        )

        bar = MockBar(symbol="BTC/USDT", close=50000.0)
        result = await monitor.validate_bar(bar)

        assert monitor.is_degraded is False
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_no_fallback_with_redis_failure_still_works(self):
        """Without fallback enabled and Redis failing, checks return neutral scores.

        When use_in_memory_fallback=False and Redis fails, _state_get returns None
        (no fallback store). Each check interprets None as 'first bar' and returns 1.0.
        This means the monitor effectively passes all bars — a known limitation when
        fallback is explicitly disabled.
        """
        failing_redis = FailingRedis()
        monitor = DataQualityMonitor(
            redis_cache=failing_redis,
            enable_prometheus=False,
            use_in_memory_fallback=False,  # Fallback disabled
        )

        bar = MockBar(symbol="BTC/USDT", close=50000.0)
        result = await monitor.validate_bar(bar)

        # Without fallback, _state_get returns None → each check sees "first bar" → 1.0
        # This is the expected (if suboptimal) behavior when fallback is disabled
        assert result.score.overall_score == pytest.approx(1.0, abs=0.01)
        # Monitor enters degraded mode because Redis was configured but failed
        assert monitor.is_degraded is True


# ---------------------------------------------------------------------------
# Test: State Isolation Between Symbols
# ---------------------------------------------------------------------------


class TestStateIsolation:
    """Tests for per-symbol state isolation in fallback mode."""

    @pytest.mark.asyncio
    async def test_different_symbols_independent(self):
        """State for different symbols is tracked independently."""
        monitor = DataQualityMonitor(
            redis_cache=None,
            enable_prometheus=False,
            use_in_memory_fallback=True,
        )

        now = time.time()
        btc_bar = MockBar(symbol="BTC/USDT", timestamp=now, close=50000.0, volume=100.0)
        eth_bar = MockBar(symbol="ETH/USDT", timestamp=now, close=3000.0, volume=500.0)

        result_btc = await monitor.validate_bar(btc_bar)
        result_eth = await monitor.validate_bar(eth_bar)

        # Both should be independently valid
        assert result_btc.valid is True
        assert result_eth.valid is True

        # Spike in BTC should not affect ETH
        btc_spike = MockBar(symbol="BTC/USDT", timestamp=now + 5, close=60000.0)
        eth_normal = MockBar(symbol="ETH/USDT", timestamp=now + 5, close=3010.0)

        result_btc2 = await monitor.validate_bar(btc_spike)
        result_eth2 = await monitor.validate_bar(eth_normal)

        assert result_btc2.score.continuity_score < 0.5  # BTC spike detected
        assert result_eth2.score.continuity_score == 1.0  # ETH unaffected
