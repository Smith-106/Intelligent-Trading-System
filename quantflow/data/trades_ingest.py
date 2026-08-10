"""Opt-in trades poll → TradesStore (W23a).

REST ``fetch_trades`` on an interval; optional callback for WS-style push.
Default posture: disabled — callers must enable and provide a fetcher.

This is **not** a production market-data bus; it is a research scaffold for
true CVD / FeatureStore columns.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import pandas as pd

from quantflow.data.trades_store import TradesStore

logger = logging.getLogger(__name__)

FetchTradesFn = Callable[..., Awaitable[pd.DataFrame]]
OnBatchFn = Callable[[str, pd.DataFrame], None]


class TradesIngestLoop:
    """Background poller that writes public trades into :class:`TradesStore`."""

    def __init__(
        self,
        store: TradesStore,
        *,
        fetch_trades: FetchTradesFn,
        symbols: Sequence[str],
        interval_s: float = 30.0,
        limit: int = 100,
        on_batch: OnBatchFn | None = None,
    ) -> None:
        self._store = store
        self._fetch_trades = fetch_trades
        self._symbols = list(symbols)
        self._interval_s = max(1.0, float(interval_s))
        self._limit = max(1, int(limit))
        self._on_batch = on_batch
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self.batches_written: int = 0
        self.rows_written: int = 0
        self.last_error: str | None = None

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    def start(self) -> asyncio.Task[None]:
        if self.is_running:
            assert self._task is not None
            return self._task
        self._running = True
        self._task = asyncio.create_task(self._loop())
        return self._task

    async def stop(self) -> None:
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def poll_once(self) -> int:
        """Fetch+save one round; returns total rows accepted by the store."""
        if not self._symbols:
            return 0
        total = 0
        for sym in self._symbols:
            try:
                df = await self._fetch_trades(sym, limit=self._limit)
            except TypeError:
                # allow fn(symbol) only
                try:
                    df = await self._fetch_trades(sym)
                except Exception as e:
                    self.last_error = str(e)
                    logger.warning("trades ingest fetch failed (%s): %s", sym, e)
                    continue
            except Exception as e:
                self.last_error = str(e)
                logger.warning("trades ingest fetch failed (%s): %s", sym, e)
                continue
            if df is None or getattr(df, "empty", True):
                continue
            n = self._store.save_trades(sym, df)
            total += n
            self.batches_written += 1
            self.rows_written += n
            if self._on_batch is not None:
                self._on_batch(sym, df)
        return total

    async def push_trades(self, symbol: str, trades: pd.DataFrame) -> int:
        """WS-style push path: persist a batch without REST fetch."""
        if trades is None or trades.empty:
            return 0
        n = self._store.save_trades(symbol, trades)
        self.batches_written += 1
        self.rows_written += n
        if self._on_batch is not None:
            self._on_batch(symbol, trades)
        return n

    async def _loop(self) -> None:
        try:
            while self._running:
                try:
                    await self.poll_once()
                except Exception as e:
                    self.last_error = str(e)
                    logger.warning("trades ingest cycle error: %s", e)
                await asyncio.sleep(self._interval_s)
        except asyncio.CancelledError:
            logger.info("Trades ingest loop cancelled")
            raise
        finally:
            self._running = False


def make_fetcher_adapter(data_fetcher: Any) -> FetchTradesFn:
    """Adapt ``DataFetcher.fetch_trades`` to the ingest signature."""

    async def _fetch(symbol: str, limit: int = 100) -> pd.DataFrame:
        return await data_fetcher.fetch_trades(symbol, limit=limit)

    return _fetch
