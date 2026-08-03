"""Unit tests for quantflow/data/market_meta_fetcher.py (T-s2-01).

Key scenarios (plan test_plan):
- RateLimiter serializes requests (>= 200 ms spacing)
- 50011 / RateLimitExceeded -> exactly 3 backoff retries (1s/2s/4s) -> DataError
- Settlement interval runtime-derived from nextFundingTime - fundingTime
- Funding history pagination advance + dedupe + non-finite drop
- OI is REST-only (no watch_* calls ever made)
- Not-connected fetch -> GatewayConnectionError (fail-closed)
- Freshness gates fail closed
"""

from __future__ import annotations

import math

import ccxt.async_support as ccxt_async
import pytest

import quantflow.data.market_meta_fetcher as mmf
from quantflow.common.config import DataConfig
from quantflow.common.exceptions import DataError, GatewayConnectionError
from quantflow.data.market_meta_fetcher import (
    FUNDING_POLL_INTERVAL_S,
    OI_MAX_AGE_S,
    OI_POLL_INTERVAL_S,
    FundingRateSnapshot,
    MarketMetaFetcher,
    OpenInterestSnapshot,
    RateLimiter,
    is_funding_fresh,
    is_oi_fresh,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeClock:
    """Deterministic monotonic clock + sleep recorder."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class MockExchange:
    """Duck-typed ccxt exchange double recording every method call."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.funding_rate_response: dict = {}
        self.funding_history_pages: list[list[dict]] = []
        self.oi_response: dict = {}
        self.oi_history_pages: list[list[dict]] = []

    async def fetchFundingRate(self, symbol: str):
        self.calls.append("fetchFundingRate")
        return self.funding_rate_response

    async def fetchFundingRateHistory(self, symbol: str, since, params):
        self.calls.append("fetchFundingRateHistory")
        if self.funding_history_pages:
            return self.funding_history_pages.pop(0)
        return []

    async def fetchOpenInterest(self, symbol: str):
        self.calls.append("fetchOpenInterest")
        return self.oi_response

    async def fetchOpenInterestHistory(self, symbol, timeframe, since, limit, params):
        self.calls.append("fetchOpenInterestHistory")
        if self.oi_history_pages:
            return self.oi_history_pages.pop(0)
        return []


@pytest.fixture
def fake_clock(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(mmf.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(mmf.asyncio, "sleep", clock.sleep)
    return clock


def _funding_entry(ts: int, rate: str = "0.0001") -> dict:
    return {
        "timestamp": ts,
        "fundingRate": rate,
        "info": {"realizedRate": rate, "fundingTime": str(ts)},
    }


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_five_acquires_keep_min_interval(self, fake_clock):
        """Adjacent acquires are spaced >= 200 ms (fake clock)."""
        limiter = RateLimiter(min_interval=0.2)
        stamps: list[float] = []
        for _ in range(5):
            await limiter.acquire()
            stamps.append(fake_clock.now)
        for prev, curr in zip(stamps, stamps[1:]):
            assert curr - prev >= 0.2

    @pytest.mark.asyncio
    async def test_first_acquire_is_immediate(self, fake_clock):
        limiter = RateLimiter()
        await limiter.acquire()
        assert fake_clock.sleeps == []  # no wait for the first slot


# ---------------------------------------------------------------------------
# Retry / backoff
# ---------------------------------------------------------------------------


class TestRetryBackoff:
    @pytest.mark.asyncio
    async def test_rate_limit_retries_three_times_then_fails(self, fake_clock):
        """RateLimitExceeded/50011 -> exactly 3 retries, backoff 1/2/4s."""
        exchange = MockExchange()

        async def boom(symbol: str):
            raise ccxt_async.RateLimitExceeded("50011 rate limit exceeded")

        exchange.fetchFundingRate = boom  # type: ignore[method-assign]
        fetcher = MarketMetaFetcher(DataConfig(), exchange=exchange)

        with pytest.raises(DataError, match="failed after 3 retries"):
            await fetcher.fetch_funding_rate("BTC/USDT:USDT")

        backoffs = [s for s in fake_clock.sleeps if s >= 0.9]
        assert len(backoffs) == 3
        for actual, base in zip(backoffs, (1.0, 2.0, 4.0)):
            assert base <= actual <= base * 1.11  # jitter tolerance

    @pytest.mark.asyncio
    async def test_non_retryable_error_raises_immediately(self, fake_clock):
        exchange = MockExchange()

        async def bad_request(symbol: str):
            raise ccxt_async.BadRequest("invalid symbol")

        exchange.fetchFundingRate = bad_request  # type: ignore[method-assign]
        fetcher = MarketMetaFetcher(DataConfig(), exchange=exchange)

        with pytest.raises(DataError, match="fetch_funding_rate"):
            await fetcher.fetch_funding_rate("NOPE/USDT")
        # No backoff sleeps for non-retryable failures.
        assert [s for s in fake_clock.sleeps if s >= 0.9] == []

    @pytest.mark.asyncio
    async def test_not_connected_raises_gateway_connection_error(self):
        fetcher = MarketMetaFetcher(DataConfig())  # no connect()
        with pytest.raises(GatewayConnectionError):
            await fetcher.fetch_funding_rate("BTC/USDT:USDT")
        with pytest.raises(GatewayConnectionError):
            await fetcher.fetch_open_interest("BTC/USDT:USDT")


# ---------------------------------------------------------------------------
# Funding rate snapshot & runtime settlement interval
# ---------------------------------------------------------------------------


class TestFundingRateSnapshot:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("interval_hours", [8, 6, 4, 2, 1])
    async def test_settlement_interval_runtime_derived(
        self, fake_clock, interval_hours: int
    ):
        """settlement_interval_ms = nextFundingTime - fundingTime (no 8h hardcode)."""
        funding_time = 1_700_000_000_000
        interval_ms = interval_hours * 3600 * 1000
        exchange = MockExchange()
        exchange.funding_rate_response = {
            "fundingRate": 0.0001,
            "fundingTimestamp": funding_time,
            "nextFundingTimestamp": funding_time + interval_ms,
            "info": {"settFundingRate": "0.00012", "settState": "settled"},
        }
        fetcher = MarketMetaFetcher(DataConfig(), exchange=exchange)

        snap = await fetcher.fetch_funding_rate("BTC/USDT:USDT")

        assert snap.settlement_interval_ms == interval_ms
        assert snap.funding_rate == pytest.approx(0.0001)
        assert snap.sett_state == "settled"
        assert snap.fetched_at_ms > 0

    @pytest.mark.asyncio
    async def test_history_pagination_advance_dedupe_and_filter(self, fake_clock):
        """limit=400 pages advance by last_ts+1, dedupe, drop non-finite."""
        base = 1_700_000_000_000
        page1 = [_funding_entry(base + i) for i in range(400)]
        page2 = [_funding_entry(base + 400 + i) for i in range(99)]
        # Duplicate of an existing ts (replay) + a non-finite rate row.
        page2.append(_funding_entry(base + 5))
        page2.append({"timestamp": base + 900, "fundingRate": None, "info": {}})

        sinces: list[int] = []

        async def paged_history(symbol: str, since, params):
            sinces.append(since)
            return [page1, page2][len(sinces) - 1]

        exchange = MockExchange()
        exchange.fetchFundingRateHistory = paged_history  # type: ignore[method-assign]
        fetcher = MarketMetaFetcher(DataConfig(), exchange=exchange)

        df = await fetcher.fetch_funding_rate_history("BTC/USDT:USDT", since_ms=base)

        assert sinces == [base, base + 400]  # pagination advances past last ts
        assert len(df) == 499  # 400 + 99 new; duplicate merged, NaN dropped
        assert list(df.columns) == mmf.FUNDING_HISTORY_COLUMNS
        assert df["timestamp"].is_monotonic_increasing
        assert df["timestamp"].is_unique
        assert df["funding_rate"].apply(math.isfinite).all()

    @pytest.mark.asyncio
    async def test_history_empty_returns_column_contract(self, fake_clock):
        exchange = MockExchange()
        fetcher = MarketMetaFetcher(DataConfig(), exchange=exchange)
        df = await fetcher.fetch_funding_rate_history("BTC/USDT:USDT", since_ms=0)
        assert df.empty
        assert list(df.columns) == mmf.FUNDING_HISTORY_COLUMNS


# ---------------------------------------------------------------------------
# Open interest (REST only)
# ---------------------------------------------------------------------------


class TestOpenInterest:
    @pytest.mark.asyncio
    async def test_fetch_open_interest_snapshot(self, fake_clock):
        exchange = MockExchange()
        exchange.oi_response = {
            "openInterest": 55000.0,
            "timestamp": 1_700_000_000_000,
            "info": {"oiCcy": "5500", "oiUsd": "200000000"},
        }
        fetcher = MarketMetaFetcher(DataConfig(), exchange=exchange)

        snap = await fetcher.fetch_open_interest("BTC/USDT:USDT")

        assert snap.open_interest == pytest.approx(55000.0)
        assert snap.open_interest_usd == pytest.approx(200_000_000.0)
        assert snap.timestamp == 1_700_000_000_000
        assert snap.fetched_at_ms > 0

    @pytest.mark.asyncio
    async def test_oi_history_pagination_period_1h(self, fake_clock):
        base = 1_700_000_000_000
        page1 = [
            {"timestamp": base + i * 3600_000, "openInterestAmount": 100.0 + i, "info": {}}
            for i in range(100)
        ]
        page2 = [
            {
                "timestamp": base + (100 + i) * 3600_000,
                "openInterestAmount": 200.0 + i,
                "openInterestUsd": 1_000_000.0,
                "info": {},
            }
            for i in range(50)
        ]
        periods: list[str] = []

        async def paged(symbol, timeframe, since, limit, params):
            periods.append(timeframe)
            return [page1, page2][0] if len(periods) == 1 else page2

        exchange = MockExchange()
        exchange.fetchOpenInterestHistory = paged  # type: ignore[method-assign]
        fetcher = MarketMetaFetcher(DataConfig(), exchange=exchange)

        df = await fetcher.fetch_open_interest_history(
            "BTC/USDT:USDT", period="1H", since_ms=base
        )

        assert periods == ["1H", "1H"]
        assert len(df) == 150
        assert list(df.columns) == mmf.OI_HISTORY_COLUMNS
        assert df["timestamp"].is_monotonic_increasing

    @pytest.mark.asyncio
    async def test_no_websocket_calls_ever(self, fake_clock):
        """OI has no WS feed — fetcher must only use REST methods."""
        exchange = MockExchange()
        exchange.funding_rate_response = {"fundingRate": 0.0, "fundingTimestamp": 1}
        exchange.oi_response = {"openInterest": 1.0, "timestamp": 1}
        fetcher = MarketMetaFetcher(DataConfig(), exchange=exchange)
        await fetcher.fetch_funding_rate("BTC/USDT:USDT")
        await fetcher.fetch_open_interest("BTC/USDT:USDT")
        assert all(not c.startswith("watch") for c in exchange.calls)


# ---------------------------------------------------------------------------
# Freshness gates (fail-closed)
# ---------------------------------------------------------------------------


class TestFreshnessGates:
    def _funding_snap(self, fetched_at_ms: int) -> FundingRateSnapshot:
        return FundingRateSnapshot(
            symbol="BTC/USDT:USDT",
            funding_rate=0.0001,
            sett_funding_rate=0.0001,
            sett_state="settled",
            funding_time=fetched_at_ms - 1000,
            next_funding_time=fetched_at_ms - 1000 + 8 * 3600 * 1000,
            fetched_at_ms=fetched_at_ms,
        )

    def test_funding_fresh_within_window(self):
        snap = self._funding_snap(1_000_000)
        assert is_funding_fresh(snap, now_ms=1_000_000 + 3600_000, settlement_interval_ms=8 * 3600_000)

    def test_funding_stale_beyond_factor(self):
        snap = self._funding_snap(1_000_000)
        # age = 2.5 x interval > 2 x interval -> stale (fail-closed)
        assert not is_funding_fresh(
            snap, now_ms=1_000_000 + int(2.5 * 8 * 3600_000),
            settlement_interval_ms=8 * 3600_000,
        )

    def test_funding_none_snapshot_or_bad_interval_is_stale(self):
        assert not is_funding_fresh(None, now_ms=1, settlement_interval_ms=8 * 3600_000)
        assert not is_funding_fresh(self._funding_snap(1), now_ms=2, settlement_interval_ms=0)
        assert not is_funding_fresh(self._funding_snap(10), now_ms=5, settlement_interval_ms=100)

    def test_oi_freshness(self):
        snap = OpenInterestSnapshot(
            symbol="BTC/USDT:USDT",
            open_interest=1.0,
            open_interest_ccy=1.0,
            open_interest_usd=1.0,
            timestamp=1,
            fetched_at_ms=1_000_000,
        )
        assert is_oi_fresh(snap, now_ms=1_000_000 + int(OI_MAX_AGE_S * 1000))
        assert not is_oi_fresh(snap, now_ms=1_000_000 + int(OI_MAX_AGE_S * 1000) + 1)
        assert not is_oi_fresh(None, now_ms=1)


# ---------------------------------------------------------------------------
# Polling-floor constants sanity (analyze locked values)
# ---------------------------------------------------------------------------


def test_polling_constants_locked():
    assert FUNDING_POLL_INTERVAL_S >= 60.0
    assert OI_POLL_INTERVAL_S >= 30.0
    assert mmf.MIN_ENDPOINT_INTERVAL_S >= 0.2
