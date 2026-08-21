"""Bybit V5 funding-rate + open-interest history via CCXT.

Reuses the rate-limit / retry scaffolding from ``market_meta_fetcher``
(``RateLimiter`` + ``_is_retryable``) so all meta endpoints share the same
IP-level serial throttle and backoff discipline. Bybit specifics:

- Funding history page cap is **200** (OKX is 100); Bybit has no
  ``realized_rate`` column — it is left ``NaN`` to satisfy the store contract.
- Open interest history **supports time-series** (``intervalTime`` + cursor
  pagination), not just a snapshot — ccxt ``fetch_open_interest_history``
  drives it, and we loop ``nextPageCursor`` ourselves for full-window pulls.
- Symbol is stored with a ``-BYBIT`` suffix (the ``.``-less ``SYMBOL_PATTERN``
  allows ``-`` but rejects ``.``), matching the OHLCV source-isolation rule.

Design consensus (three-model P2 review 2026-08-21): deepseek + GLM confirmed
the endpoints; hy3 was unavailable (provider weekly quota exhausted).
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Callable
from typing import Any

import ccxt.async_support as ccxt
import pandas as pd

from quantflow.common.config import DataConfig
from quantflow.common.exceptions import DataError, GatewayConnectionError
from quantflow.data.bybit_common import bybit_market_id, bybit_store_symbol
from quantflow.data.market_meta_fetcher import (
    BASE_BACKOFF_S,
    CALL_TIMEOUT,
    MAX_RETRIES,
    MIN_ENDPOINT_INTERVAL_S,
    RateLimiter,
    _is_retryable,
    _to_float,
)
from quantflow.data.store import DataStore

logger = logging.getLogger(__name__)

BYBIT_FUNDING_PAGE_MAX = 200  # ccxt.bybit funding-history page cap (OKX is 100)
BYBIT_OI_PAGE_MAX = 200  # open-interest history page cap
BYBIT_MARK_PAGE_MAX = 1000  # mark-price-kline page cap (V5 kline-style endpoint)

# OI ``intervalTime`` -> mark-price-kline ``interval`` enums differ in V5.
BYBIT_MARK_INTERVAL_MAP = {
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "4h": "240",
    "1d": "D",
}

# RV-007-007 fix: the OI endpoint's ``intervalTime`` enum uses ``5min``-style
# tokens below 1h (unlike kline intervals) — passing '5m' is rejected by the API.
BYBIT_OI_INTERVAL_MAP = {
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}


async def _retry_call(limiter: RateLimiter, factory: Callable[[], Any], op: str) -> Any:
    """Run an endpoint call with IP-level rate limiting and bounded retry.

    Mirrors ``MarketMetaFetcher._retry_call`` (shared decision: self-throttle,
    do NOT rely on ccxt built-in limiting). Retryable failures back off
    1s -> 2s -> 4s with jitter, then raise ``DataError`` (fail-closed).
    """
    delay = BASE_BACKOFF_S
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            await limiter.acquire()
            return await asyncio.wait_for(factory(), timeout=CALL_TIMEOUT)
        except Exception as e:
            if not _is_retryable(e):
                raise DataError(f"{op} failed: {e}") from e
            last_exc = e
            if attempt >= MAX_RETRIES:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, 4.0)
    raise DataError(f"{op} failed after {MAX_RETRIES} retries: {last_exc}") from last_exc


class BybitMetaFetcher:
    """Fetch Bybit V5 funding-rate / open-interest history (CCXT, category=linear).

    A single instance owns one ``ccxt.bybit`` exchange object; share one
    instance across a session (M4-1.2 invariant).
    """

    def __init__(
        self, config: DataConfig, category: str = "linear", exchange: Any | None = None
    ) -> None:
        self._config = config
        self._category = category
        self._exchange: Any | None = exchange
        self._owns_exchange = exchange is None
        self._limiter = RateLimiter(MIN_ENDPOINT_INTERVAL_S)

    async def connect(self) -> None:
        if self._exchange is not None:
            return
        try:
            # RV-007-020/M1: pre-bind so a constructor failure can be cleaned up.
            exchange: ccxt.bybit | None = None
            exchange = ccxt.bybit({"options": {"defaultType": self._category}})
            # Bybit load_markets probes all categories and the option probe can
            # 400 in some regions; fetch_* resolves symbols lazily and does not
            # require a populated markets cache — non-fatal.
            try:
                await asyncio.wait_for(exchange.load_markets(), timeout=CALL_TIMEOUT)
                logger.info("BybitMetaFetcher connected (markets loaded)")
            except Exception as e:
                logger.warning("BybitMetaFetcher load_markets skipped: %s", e)
            self._exchange = exchange
        except Exception as e:
            # RV-007-020/M1: construction itself may have failed — exchange is
            # then unbound; guard the cleanup instead of masking with NameError.
            if exchange is not None:
                try:
                    await exchange.close()
                except Exception:
                    logger.debug("BybitMetaFetcher close after connect failure", exc_info=True)
            raise GatewayConnectionError(f"Failed to connect Bybit meta fetcher: {e}") from e

    async def disconnect(self) -> None:
        if self._exchange is not None and self._owns_exchange:
            try:
                await self._exchange.close()
            except Exception:
                logger.debug("BybitMetaFetcher close failed", exc_info=True)
        self._exchange = None

    def _require_exchange(self) -> Any:
        if self._exchange is None:
            raise GatewayConnectionError("Not connected. Call connect() first.")
        return self._exchange

    # ------------------------------------------------------------------
    # Funding rate history
    # ------------------------------------------------------------------

    async def fetch_funding_rate_history(
        self, symbol: str, since_ms: int, limit: int = 200
    ) -> pd.DataFrame:
        """Backfill Bybit funding-rate history (1 settlement per 8h).

        Uses the native V5 ``/v5/market/funding/history`` endpoint (category
        passed explicitly) — ccxt's unified ``fetchFundingRateHistory`` resolves
        ``BTC/USDT`` to spot and rejects it. Returns the store ``funding_rate``
        contract ``[timestamp, funding_rate, realized_rate, funding_time]``.
        Bybit has no ``realized_rate`` concept, so that column is ``NaN``.
        """
        exchange = self._require_exchange()
        # Native V5 market id: BTC/USDT -> BTCUSDT,
        # BTC/USDT:USDT-260904 -> BTCUSDT260904.
        bsym = bybit_market_id(symbol)
        effective_limit = min(limit, BYBIT_FUNDING_PAGE_MAX)
        all_rows: list[dict[str, Any]] = []
        # RV-007-001 fix: advance by hard time windows instead of relying on a
        # full-page signal. The endpoint returns newest-first, so at ~90 8h
        # settlements per 30d window a full page never materialises and the
        # old len(page) < limit check silently stopped after the first window.
        now_ms = int(time.time() * 1000)
        window_ms = 30 * 86_400_000
        since = int(since_ms)
        pages = 0
        while since < now_ms:
            pages += 1
            if pages > 500:
                logger.warning("Bybit funding pagination exceeded 500 pages for %s", symbol)
                break

            window_start = since

            def _call(s: int = window_start) -> Any:
                # Bybit funding/history requires both startTime AND endTime.
                e = min(now_ms, s + window_ms)
                return exchange.request(
                    "/v5/market/funding/history",
                    "public",
                    "GET",
                    {
                        "category": self._category,
                        "symbol": bsym,
                        "startTime": s,
                        "endTime": e,
                        "limit": effective_limit,
                    },
                )

            resp = await _retry_call(self._limiter, _call, f"bybit.funding_history:{symbol}")
            result = resp.get("result", {}) if isinstance(resp, dict) else {}
            page = result.get("list", []) if isinstance(result, dict) else []
            for entry in page or []:
                # entry: [fundingRate, fundingRateTimestamp] (list form)
                if isinstance(entry, list):
                    rate = _to_float(entry[0], default=math.nan)
                    ts = int(entry[1])
                else:
                    rate = _to_float(entry.get("fundingRate"), default=math.nan)
                    ts = int(entry.get("fundingRateTimestamp", entry.get("timestamp", 0)))
                all_rows.append(
                    {
                        "timestamp": ts,
                        "funding_rate": rate,
                        # Bybit has no realized_rate — NaN keeps the contract
                        # (store validates the column exists, not its values).
                        "realized_rate": float("nan"),
                        "funding_time": ts,
                    }
                )
            # Advance unconditionally — empty windows must not stall the walk.
            since += window_ms

        if not all_rows:
            return pd.DataFrame(
                columns=["timestamp", "funding_rate", "realized_rate", "funding_time"]
            )
        df = pd.DataFrame(all_rows)
        # Deduplicate by timestamp, sort ascending.
        df = (
            df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        )
        logger.info("Bybit funding history: %d rows for %s", len(df), symbol)
        return df

    # ------------------------------------------------------------------
    # Open interest history
    # ------------------------------------------------------------------

    async def fetch_mark_price_kline(
        self,
        symbol: str,
        timeframe: str = "1h",
        since_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 200,
    ) -> pd.DataFrame:
        """Fetch the mark-price time series (V5 ``/v5/market/mark-price-kline``).

        Returns ``[timestamp, mark_price]`` where ``mark_price`` is the bucket
        OPEN (the price at the interval start — the instant an OI sample is
        stamped). Shares the instance limiter/exchange with funding/OI.
        """
        exchange = self._require_exchange()
        interval = BYBIT_MARK_INTERVAL_MAP.get(timeframe)
        if interval is None:
            raise DataError(
                f"Unsupported mark-price timeframe: {timeframe}. Valid: {sorted(BYBIT_MARK_INTERVAL_MAP)}"
            )
        bsym = bybit_market_id(symbol)
        effective_limit = min(limit, BYBIT_MARK_PAGE_MAX)
        end = end_ms if end_ms is not None else int(time.time() * 1000)
        cursor_start = since_ms if since_ms is not None else end - 7 * 86_400_000
        all_rows: list[dict[str, Any]] = []
        pages = 0
        while True:
            pages += 1
            if pages > 500:
                logger.warning("Bybit mark-price pagination exceeded 500 pages for %s", symbol)
                break

            def _call(s: int = cursor_start) -> Any:
                return exchange.request(
                    "/v5/market/mark-price-kline",
                    "public",
                    "GET",
                    {
                        "category": self._category,
                        "symbol": bsym,
                        "interval": interval,
                        "startTime": s,
                        "endTime": end,
                        "limit": effective_limit,
                    },
                )

            resp = await _retry_call(self._limiter, _call, f"bybit.mark_kline:{symbol}")
            result = resp.get("result", {}) if isinstance(resp, dict) else {}
            records = result.get("list", []) if isinstance(result, dict) else []
            if not records:
                break
            # V5 kline list form: [startTime, open, high, low, close] (strings).
            for entry in records:
                ts = int(entry[0])
                all_rows.append(
                    {"timestamp": ts, "mark_price": _to_float(entry[1], default=math.nan)}
                )
                # RV-007-014: 0.0 is a legal mark/OI value — parse failures must
                # surface as NaN, not masquerade as legitimate zeros.
            last_ts = max(int(e[0]) for e in records)
            if len(records) < effective_limit:
                break
            cursor_start = last_ts + 1

        if not all_rows:
            return pd.DataFrame(columns=["timestamp", "mark_price"])
        df = (
            pd.DataFrame(all_rows)
            .drop_duplicates(subset=["timestamp"])
            .sort_values("timestamp")
            .reset_index(drop=True)
        )
        logger.info("Bybit mark-price kline: %d rows for %s", len(df), symbol)
        return df

    async def fetch_open_interest_history(
        self,
        symbol: str,
        timeframe: str = "1h",
        since_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 200,
        *,
        mark_usd: bool = True,
    ) -> pd.DataFrame:
        """Backfill Bybit open-interest history (time-series, not snapshot).

        Bybit ``/v5/market/open-interest`` supports ``intervalTime`` + cursor
        pagination and returns a full historical window (1D reaches back to
        ~2022, far deeper than OKX rubik). Returns the store ``open_interest``
        contract ``[timestamp, open_interest, open_interest_ccy, open_interest_usd]``.

        With ``mark_usd=True`` (default) the USD column is computed as
        ``open_interest x mark_price`` using the mark-price-kline series aligned
        on the shared interval-start timestamp (backward, tolerance = one
        interval). Mark failures degrade softly: WARNING + NaN, base OI intact.
        """
        exchange = self._require_exchange()
        effective_limit = min(limit, BYBIT_OI_PAGE_MAX)
        all_rows: list[dict[str, Any]] = []
        cursor: str | None = None
        pages = 0
        while True:
            pages += 1
            if pages > 500:
                logger.warning("Bybit OI pagination exceeded 500 pages for %s", symbol)
                break

            def _call(
                c: str | None = cursor,
                s: int | None = since_ms,
                e: int | None = end_ms,
            ) -> Any:
                # Native V5 endpoint — ccxt's fetch_open_interest_history
                # resolves BTC/USDT to spot and rejects it; pass category + the
                # full time window explicitly.
                params: dict[str, Any] = {
                    "category": self._category,
                    "symbol": bybit_market_id(symbol),
                    # RV-007-007: V5 intervalTime enum is '5min'-style below 1h.
                    "intervalTime": BYBIT_OI_INTERVAL_MAP[timeframe],
                    "limit": effective_limit,
                }
                # Bybit open-interest requires startTime AND endTime. Use a
                # bounded window (7d for 1h granularity) ending at end_ms/now.
                end = e if e is not None else int(time.time() * 1000)
                start = s if s is not None else end - 7 * 86_400_000
                params["startTime"] = start
                params["endTime"] = end
                if c:
                    params["cursor"] = c
                return exchange.request("/v5/market/open-interest", "public", "GET", params)

            resp = await _retry_call(self._limiter, _call, f"bybit.oi_history:{symbol}")
            result = resp.get("result", {}) if isinstance(resp, dict) else {}
            page = result if isinstance(result, dict) else {}
            records = page.get("list", []) if isinstance(page, dict) else []
            if not records:
                break
            for entry in records:
                ts = int(entry["timestamp"])
                oi = _to_float(entry.get("openInterest"))
                all_rows.append(
                    {
                        "timestamp": ts,
                        "open_interest": oi,
                        "open_interest_ccy": oi,  # Bybit linear unit = base asset
                        "open_interest_usd": float("nan"),  # not provided by Bybit
                    }
                )
            next_cursor = page.get("nextPageCursor") if isinstance(page, dict) else None
            if not next_cursor or len(records) < effective_limit:
                break
            cursor = next_cursor

        if not all_rows:
            return pd.DataFrame(
                columns=["timestamp", "open_interest", "open_interest_ccy", "open_interest_usd"]
            )
        df = pd.DataFrame(all_rows)
        df = (
            df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        )

        if mark_usd:
            df = await self._enrich_oi_usd(df, symbol, timeframe)

        logger.info("Bybit OI history: %d rows for %s", len(df), symbol)
        return df

    async def _enrich_oi_usd(
        self, oi_df: pd.DataFrame, symbol: str, timeframe: str
    ) -> pd.DataFrame:
        """Fill ``open_interest_usd`` = OI(base) x mark_price (soft-degrade).

        Alignment: both series are stamped at the interval start, so a backward
        merge with tolerance of one interval is exact for complete data; gaps
        beyond tolerance stay NaN rather than being silently filled.
        """
        interval_ms = {
            "5m": 300_000,
            "15m": 900_000,
            "30m": 1_800_000,
            "1h": 3_600_000,
            "4h": 14_400_000,
            "1d": 86_400_000,
        }[timeframe]
        try:
            mark_df = await self.fetch_mark_price_kline(
                symbol,
                timeframe,
                int(oi_df["timestamp"].min()),
                int(oi_df["timestamp"].max()) + interval_ms,
            )
        except Exception as e:
            logger.warning(
                "Mark-price fetch failed for %s; open_interest_usd stays NaN: %s", symbol, e
            )
            return oi_df
        if mark_df.empty:
            logger.warning("No mark-price data for %s; open_interest_usd stays NaN", symbol)
            return oi_df
        merged = pd.merge_asof(
            oi_df.sort_values("timestamp"),
            mark_df.sort_values("timestamp"),
            on="timestamp",
            direction="backward",
            tolerance=interval_ms,
        )
        usd = merged["open_interest"] * merged["mark_price"]
        oi_df = oi_df.copy()
        oi_df["open_interest_usd"] = pd.to_numeric(usd, errors="coerce")
        filled = int(oi_df["open_interest_usd"].notna().sum())
        if filled < len(oi_df):
            logger.warning(
                "OI USD: %d/%d rows matched a mark price for %s (rest stay NaN)",
                filled,
                len(oi_df),
                symbol,
            )
        return oi_df

    # ------------------------------------------------------------------
    # Store helpers (suffix-isolated)
    # ------------------------------------------------------------------

    def save_funding(self, store: DataStore, df: pd.DataFrame, symbol: str) -> None:
        """Persist funding history under the validator-safe Bybit store key."""
        if df.empty:
            return
        store.save_funding_rates(df, bybit_store_symbol(symbol))

    def save_open_interest(self, store: DataStore, df: pd.DataFrame, symbol: str) -> None:
        """Persist OI history under the validator-safe Bybit store key."""
        if df.empty:
            return
        store.save_open_interest(df, bybit_store_symbol(symbol))
