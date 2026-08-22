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

import ccxt.async_support as ccxt
import pandas as pd

from quantflow.common.config import DataConfig
from quantflow.common.exceptions import DataError, GatewayConnectionError

logger = logging.getLogger(__name__)

# Bybit V5 kline cap is 1000 bars per request (OKX is 300).
BYBIT_KLINE_PAGE_MAX = 1000

# Per-call timeout for every CCXT network call (odyssey-improve GP2).
CALL_TIMEOUT = 30.0



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

        from quantflow.data.fetcher import fetch_ohlcv_paginated

        return await fetch_ohlcv_paginated(
            self._exchange,
            symbol,
            timeframe,
            start,
            end,
            limit,
            page_max=BYBIT_KLINE_PAGE_MAX,
            log_prefix="Bybit fetched",
        )

