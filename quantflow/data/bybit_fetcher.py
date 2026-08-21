"""Bybit V5 historical klines via CCXT.

Mirrors the OKX ``DataFetcher`` lifecycle (connect → fetch → disconnect) so the
shared ``clean_ohlcv`` → ``DataStore.save`` pipeline ingests Bybit data through
the same path as OKX / Binance.

Design (consensus: three-model review 2026-08-21):
- CCXT over native requests (zero new dependency, uniform OHLCV shape).
- Page cap 1000 (Bybit V5), OKX-style ``since`` cursor pagination.
- Symbol stored with a ``-BYBIT`` suffix (the ``.``-less ``SYMBOL_PATTERN``
  allows ``-`` but rejects ``.``), keeping source isolation without touching
  the validator.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import ccxt.async_support as ccxt
import pandas as pd

from quantflow.common.config import DataConfig
from quantflow.common.exceptions import DataError, GatewayConnectionError

logger = logging.getLogger(__name__)

# Bybit V5 kline cap is 1000 bars per request (OKX is 300).
BYBIT_KLINE_PAGE_MAX = 1000

# Safety cap on pagination loops (mirrors OKX fetcher).
MAX_PAGINATION_PAGES = 500

# Per-call timeout for every CCXT network call (odyssey-improve GP2).
CALL_TIMEOUT = 30.0


def _bar_is_finite(bar: list[Any]) -> bool:
    """Return True if every numeric OHLCV field of a CCXT bar is finite."""
    try:
        for v in bar[:6]:
            f = float(v)
            if not __import__("math").isfinite(f):
                return False
        return True
    except (TypeError, ValueError):
        return False


class BybitFetcher:
    """Fetch historical OHLCV from Bybit V5 through CCXT.

    A single instance owns one ``ccxt.bybit`` exchange object; share one
    instance across all symbols like the OKX ``DataFetcher`` (per-instance
    rate limiter — M4-1.2 invariant).
    """

    def __init__(self, config: DataConfig, *, category: str = "spot") -> None:
        self._config = config
        self._category = category
        self._exchange: ccxt.bybit | None = None

    async def connect(self) -> None:
        try:
            self._exchange = ccxt.bybit(
                {
                    "enableRateLimit": True,
                    "rateLimit": 1000 / max(self._config.rate_limit, 1),
                    "options": {"defaultType": self._category},
                }
            )
            # load_markets is best-effort: CCXT's bybit load probes all
            # categories (spot/linear/inverse/option) and the option probe can
            # 400 on some regions, but fetch_ohlcv resolves symbols lazily and
            # does not require a populated markets cache — so a load failure is
            # non-fatal.
            try:
                await asyncio.wait_for(self._exchange.load_markets(), timeout=CALL_TIMEOUT)
                logger.info("Connected to Bybit, %d markets loaded", len(self._exchange.markets))
            except Exception as e:
                logger.warning("Bybit load_markets skipped: %s", e)
        except Exception as e:
            if self._exchange is not None:
                try:
                    await self._exchange.close()
                except Exception:
                    logger.debug("Failed to close Bybit exchange after error", exc_info=True)
                finally:
                    self._exchange = None
            raise GatewayConnectionError(f"Failed to connect to Bybit: {e}") from e

    async def disconnect(self) -> None:
        if self._exchange is not None:
            try:
                await self._exchange.close()
            except Exception:
                logger.debug("Error closing Bybit exchange", exc_info=True)
            finally:
                self._exchange = None

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        start: str | None = None,
        end: str | None = None,
        limit: int = 1000,
        *,
        category: str | None = None,
    ) -> pd.DataFrame:
        """Fetch OHLCV kline data from Bybit V5.

        category: ``spot`` / ``linear`` (USDT perp) / ``inverse``. Defaults to
        the instance category. Returns a frame with the shared column contract
        ``[timestamp, open, high, low, close, volume, symbol, timeframe, datetime]``.
        """
        if self._exchange is None:
            raise GatewayConnectionError("Not connected. Call connect() first.")
        if timeframe not in (
            "1m",
            "3m",
            "5m",
            "15m",
            "30m",
            "1h",
            "2h",
            "4h",
            "6h",
            "12h",
            "1d",
            "1w",
            "1M",
        ):
            raise DataError(f"Invalid timeframe: {timeframe}.")

        cat = category or self._category
        # RV-007-004: set unconditionally — a conditional write left the shared
        # exchange stuck on the last non-default category (silent cross-market
        # data), and concurrent multi-category calls would race on this dict.
        self._exchange.options["defaultType"] = cat

        since = None
        if start:
            since = self._exchange.parse8601(f"{start}T00:00:00Z")
        end_ts = self._exchange.parse8601(f"{end}T23:59:59Z") if end else None
        effective_limit = min(limit, BYBIT_KLINE_PAGE_MAX)

        all_bars: list[list[Any]] = []
        pages = 0
        while True:
            pages += 1
            if pages > MAX_PAGINATION_PAGES:
                logger.warning(
                    "Pagination exceeded %d pages for %s/%s; stopping",
                    MAX_PAGINATION_PAGES,
                    symbol,
                    timeframe,
                )
                break
            bars = await asyncio.wait_for(
                self._exchange.fetch_ohlcv(
                    symbol,
                    timeframe,
                    since=since,
                    limit=effective_limit,
                ),
                timeout=CALL_TIMEOUT,
            )
            if not bars:
                break
            bars = [b for b in bars if _bar_is_finite(b)]
            if not bars:
                logger.warning(
                    "All fetched bars for %s/%s were non-finite; skipped", symbol, timeframe
                )
                break
            all_bars.extend(bars)
            last_ts = bars[-1][0]
            if end_ts is not None:
                if last_ts >= end_ts:
                    all_bars = [b for b in all_bars if b[0] <= end_ts]
                    break
                since = last_ts + 1
                continue
            since = last_ts + 1
            if len(bars) < effective_limit:
                break

        df = pd.DataFrame(all_bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["symbol"] = symbol
        df["timeframe"] = timeframe
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = (
            df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        )
        logger.info("Bybit fetched %d bars for %s/%s", len(df), symbol, timeframe)
        return df

    async def fetch_ohlcv_multi(
        self,
        symbols: list[str],
        timeframe: str = "1d",
        start: str | None = None,
        end: str | None = None,
        *,
        max_concurrency: int = 1,
        on_symbol_error: Callable[[str, Exception], None] | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Fetch many symbols over a shared single instance.

        ``max_concurrency=1`` keeps the per-instance rate limiter authoritative
        (M4-1.2). A failing symbol is reported via ``on_symbol_error`` and
        omitted from the result rather than aborting the whole batch.
        """
        sem = asyncio.Semaphore(max_concurrency)

        async def _one(sym: str) -> pd.DataFrame | None:
            async with sem:
                try:
                    return await self.fetch_ohlcv(sym, timeframe, start, end)
                except Exception as e:
                    logger.warning("Bybit fetch failed for %s: %s", sym, e)
                    if on_symbol_error:
                        on_symbol_error(sym, e)
                    return None

        results = await asyncio.gather(*[_one(s) for s in symbols])
        return {
            sym: df
            for sym, df in zip(symbols, results, strict=True)
            if df is not None and not df.empty
        }
