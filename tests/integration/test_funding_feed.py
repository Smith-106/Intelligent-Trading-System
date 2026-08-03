"""Integration tests for the T-s2-04 funding/OI meta feed closed loop.

Covers the analyze-locked contracts:
- feed populates the funding_rate strategy instance and publishes
  EVENT_FUNDING / EVENT_OI telemetry (locally defined in strategy/engine.py)
- fail-closed freshness gate: stale/missing meta data blocks NEW entries
  only — exits (FLAT) keep working so open positions stay closeable
- funding_feed_enabled=false (default) -> zero behavior change
- per-symbol fetch failures and connect failures are isolated (log-only),
  they must never interrupt the feed or the main data loop
"""

from __future__ import annotations

import asyncio
import time

import pytest

from quantflow.common.config import AppConfig
from quantflow.common.event_bus import EVENT_SIGNAL
from quantflow.common.models import Bar, Direction
from quantflow.data.dq_monitor import DataQualityMonitor
from quantflow.data.market_meta_fetcher import FundingRateSnapshot, OpenInterestSnapshot
from quantflow.strategy.engine import EVENT_FUNDING, EVENT_OI, TradingSession
from quantflow.strategy.templates.funding_rate import FundingRateStrategy

SYMBOL = "BTC/USDT"
_EIGHT_H_MS = 8 * 3600 * 1000


class FakeMetaFetcher:
    """Scripted MarketMetaFetcher stand-in (no network)."""

    def __init__(
        self,
        *,
        funding_rate: float = -0.002,
        fail_connect: bool = False,
        fail_funding: bool = False,
    ) -> None:
        self.funding_rate = funding_rate
        self.fail_connect = fail_connect
        self.fail_funding = fail_funding
        self.connected = False
        self.funding_calls = 0
        self.oi_calls = 0

    async def connect(self) -> None:
        if self.fail_connect:
            raise ConnectionError("meta endpoint unreachable")
        self.connected = True

    async def fetch_funding_rate(self, symbol: str) -> FundingRateSnapshot:
        self.funding_calls += 1
        if self.fail_funding:
            raise ConnectionError(f"funding fetch failed for {symbol}")
        now_ms = int(time.time() * 1000)
        return FundingRateSnapshot(
            symbol=symbol,
            funding_rate=self.funding_rate,
            sett_funding_rate=self.funding_rate,
            sett_state="success",
            funding_time=now_ms - _EIGHT_H_MS,
            next_funding_time=now_ms,  # settled just now -> interval = 8h
            fetched_at_ms=now_ms,
        )

    async def fetch_open_interest(self, symbol: str) -> OpenInterestSnapshot:
        self.oi_calls += 1
        now_ms = int(time.time() * 1000)
        # Monotone +5%/sample so oi pct_change(3) > 5% (entry confirmation).
        oi = 1000.0 * (1.05**self.oi_calls)
        return OpenInterestSnapshot(
            symbol=symbol,
            open_interest=oi,
            open_interest_ccy=oi,
            open_interest_usd=oi * 50_000.0,
            timestamp=now_ms,
            fetched_at_ms=now_ms,
        )


def _make_session(
    fetcher: FakeMetaFetcher, *, feed_enabled: bool = True
) -> tuple[TradingSession, list[dict]]:
    config = AppConfig()
    config.execution.funding_feed_enabled = feed_enabled
    session = TradingSession(config, [FundingRateStrategy()])
    session._meta_fetcher = fetcher
    session._dq_monitor = DataQualityMonitor(enable_prometheus=False)
    signals: list[dict] = []
    session.event_bus.subscribe(EVENT_SIGNAL, lambda e: signals.append(e.data))
    return session, signals


def _flat_bar(i: int, close: float = 50_000.0) -> Bar:
    """Sideways bar — keeps the ADX regime detector non-trending."""
    return Bar(
        symbol=SYMBOL,
        timestamp=1_700_000_000_000 + i * 3_600_000,
        open=close,
        high=close + 5.0,
        low=close - 5.0,
        close=close + (3.0 if i % 2 else -3.0),
        volume=10.0,
    )


async def _fill_feed(session: TradingSession, rounds: int = 16) -> None:
    """Push enough funding/OI samples for the strategy's min_bars (16)."""
    for _ in range(rounds):
        await session._meta_poll_funding([SYMBOL])
        await session._meta_poll_oi([SYMBOL])


class TestMetaFeedClosedLoop:
    @pytest.mark.asyncio
    async def test_feed_populates_strategy_and_publishes_events(self) -> None:
        fetcher = FakeMetaFetcher()
        session, _ = _make_session(fetcher)
        funding_events: list[dict] = []
        oi_events: list[dict] = []
        session.event_bus.subscribe(EVENT_FUNDING, lambda e: funding_events.append(e.data))
        session.event_bus.subscribe(EVENT_OI, lambda e: oi_events.append(e.data))

        await session.start(mode="paper", symbols=[SYMBOL])
        try:
            assert session._meta_feed_task is not None  # feed spawned
            await _fill_feed(session)
            instance = session._instances[("funding_rate", SYMBOL)]
            assert len(instance._funding_rates) >= 16
            assert len(instance._open_interests) >= 16
            meta = session._meta_fresh[SYMBOL]
            assert meta["funding"] is True
            assert meta["oi"] is True
            assert meta["settled_interval_ms"] == _EIGHT_H_MS
            assert len(funding_events) >= 16
            assert funding_events[-1]["funding_rate"] == pytest.approx(-0.002)
            assert len(oi_events) >= 16
            assert session._meta_data_fresh(SYMBOL) is True
        finally:
            await session.stop()
        assert session._meta_feed_task is None or session._meta_feed_task.cancelled()

    @pytest.mark.asyncio
    async def test_stale_feed_blocks_entries_but_allows_exits(self) -> None:
        """Fail-closed gate: stale funding blocks NEW entries, exits pass."""
        fetcher = FakeMetaFetcher()
        session, signals = _make_session(fetcher)
        await session.start(mode="paper", symbols=[SYMBOL])
        try:
            await _fill_feed(session)
            # Drain the background loop's first cycle (create_task defers its
            # first step to the next event-loop turn) so a late first poll
            # cannot refresh the sample we are about to age.
            await asyncio.sleep(0.05)
            assert session._meta_data_fresh(SYMBOL) is True
            # Age the funding sample past 2x settlement interval (16h).
            session._meta_fresh[SYMBOL]["funding_at_ms"] = (
                int(time.time() * 1000) - 17 * 3600 * 1000
            )
            assert session._meta_data_fresh(SYMBOL) is False

            instance = session._instances[("funding_rate", SYMBOL)]
            for i in range(20):
                await session.on_bar(_flat_bar(i))
            # Entry conditions are met (rate=-0.002, OI rising) but the gate
            # must swallow them: no entry signal, no position opened.
            assert not any(s["direction"] == Direction.LONG.value for s in signals)
            assert instance._in_position is False
            assert instance._freshness_gate is False

            # Exit path stays open: force an open position and feed neutral
            # funding so the neutral-zone (or max-holding) exit fires even
            # though the feed is still stale.
            instance._in_position = True
            instance._entry_direction = Direction.LONG
            instance._entry_price = 50_000.0
            instance._bars_since_entry = 0
            for i in range(12):
                instance.update_funding_rate(0.0)
                await session.on_bar(_flat_bar(20 + i))
            assert instance._in_position is False  # exit NOT gated
            assert session._meta_data_fresh(SYMBOL) is False
        finally:
            await session.stop()

    @pytest.mark.asyncio
    async def test_cold_start_no_data_blocks_entries(self) -> None:
        """Feed enabled but never produced data -> fail-closed on entries."""
        # Failing fetcher = the feed never yields a sample (connect + fetch
        # errors are isolated, log-only).
        fetcher = FakeMetaFetcher(fail_connect=True, fail_funding=True)
        session, signals = _make_session(fetcher)
        await session.start(mode="paper", symbols=[SYMBOL])
        try:
            instance = session._instances[("funding_rate", SYMBOL)]
            # Pre-populate strategy data directly (as a backfill would) — the
            # entry math is satisfied, but the session-level gate must block.
            for i in range(16):
                instance.update_funding_rate(-0.002)
                instance.update_open_interest(1000.0 * (1.05**i))
            for i in range(18):
                await session.on_bar(_flat_bar(i))
            assert not signals
            assert instance._in_position is False
        finally:
            await session.stop()


class TestFeedDisabledZeroChange:
    @pytest.mark.asyncio
    async def test_disabled_feed_spawns_no_task_and_entries_flow(self) -> None:
        fetcher = FakeMetaFetcher()
        session, signals = _make_session(fetcher, feed_enabled=False)
        await session.start(mode="paper", symbols=[SYMBOL])
        try:
            assert session._meta_feed_task is None
            instance = session._instances[("funding_rate", SYMBOL)]
            for i in range(16):
                instance.update_funding_rate(-0.002)
                instance.update_open_interest(1000.0 * (1.05**i))
            for i in range(18):
                await session.on_bar(_flat_bar(i))
            # Gate default True + no session override -> baseline entry fires.
            assert any(
                s["direction"] == Direction.LONG.value and s["strategy_id"] == "funding_rate"
                for s in signals
            )
            assert instance._in_position is True
            assert fetcher.funding_calls == 0  # feed never touched the fetcher
        finally:
            await session.stop()


class TestFetchFailureIsolation:
    @pytest.mark.asyncio
    async def test_funding_fetch_error_isolated_oi_still_flows(self) -> None:
        fetcher = FakeMetaFetcher(fail_funding=True)
        session, _ = _make_session(fetcher)
        await session.start(mode="paper", symbols=[SYMBOL])
        try:
            # Funding raises per symbol -> swallowed; OI unaffected.
            await session._meta_poll_funding([SYMBOL])
            await session._meta_poll_oi([SYMBOL])
            assert SYMBOL not in session._meta_fresh or not session._meta_fresh[SYMBOL].get(
                "funding"
            )
            assert session._meta_fresh[SYMBOL]["oi"] is True
            assert session._meta_data_fresh(SYMBOL) is False  # fail closed
        finally:
            await session.stop()

    @pytest.mark.asyncio
    async def test_connect_failure_does_not_kill_feed_loop(self) -> None:
        fetcher = FakeMetaFetcher(fail_connect=True)
        session, _ = _make_session(fetcher)
        await session.start(mode="paper", symbols=[SYMBOL])
        try:
            assert session._meta_feed_task is not None
            await asyncio.sleep(0.2)
            assert not session._meta_feed_task.done()  # loop survived connect error
        finally:
            await session.stop()
