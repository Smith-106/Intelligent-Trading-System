"""Market meta-data fetcher — funding rate & open interest (T-s2-01).

Separate from :mod:`quantflow.data.fetcher` (OHLCV main path) so meta
collection never disturbs the bar feed. Design locked by the analyze run
(OKX rate-limit verification, C-series findings):

- **Self rate-limiting**: every endpoint call goes through an in-house
  :class:`RateLimiter` (>= 200 ms between ANY two requests, IP-level serial).
  We deliberately do NOT rely on ccxt's built-in throttler — the limiter is
  shared across funding + OI endpoints and survives instance injection.
- **Polling floors**: funding >= 60 s, open interest >= 30 s (OKX
  funding-rate 10 req/2 s, OI 20 req/2 s — floors keep us well inside).
- **Retry**: HTTP 50011 / network errors get exponential backoff
  1 s -> 2 s -> 4 s (+ jitter), max 3 retries, then ``DataError``
  (fail-closed: callers decide the degraded posture).
- **Settlement period is runtime-derived**: ``nextFundingTime - fundingTime``
  — never a hardcoded 8 h (OKX runs 8 h but the contract must not assume it).
- **OI is REST-only**: ccxt pro has no watchOpenInterest; OI freshness is a
  polling concern (see ``OI_MAX_AGE_S``).

Layering: L1 data module. Depends only on ``quantflow.common``; the ccxt
exchange instance is injected (shared with DataFetcher per M4-1.2) or
self-owned via :meth:`connect`.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import ccxt.async_support as ccxt
import pandas as pd

from quantflow.common.config import DataConfig
from quantflow.common.exceptions import DataError, GatewayConnectionError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Derived constants (source: analyze run OKX rate-limit verification).
# ---------------------------------------------------------------------------
#: Minimum interval between funding-rate polls (OKX allows 10 req/2 s; the
#: live feed needs at most one fresh sample per settlement check).
FUNDING_POLL_INTERVAL_S = 60.0
#: Minimum interval between open-interest polls (OI 20 req/2 s; 30 s keeps
#: the loop cheap while staying inside ``OI_MAX_AGE_S``).
OI_POLL_INTERVAL_S = 30.0
#: Minimum spacing between ANY two endpoint requests (IP-level serial).
MIN_ENDPOINT_INTERVAL_S = 0.2
#: Funding staleness threshold = factor x settlement interval (runtime).
FUNDING_MAX_AGE_FACTOR = 2
#: OI staleness threshold in seconds (REST-only feed, no WS available).
OI_MAX_AGE_S = 600.0
#: OKX rate-limit error code (HTTP 50011) treated as retryable.
RATE_LIMIT_ERROR_CODE = "50011"
#: Max retry attempts after the initial call (backoff 1s/2s/4s + jitter).
MAX_RETRIES = 3
#: Base backoff delay in seconds (doubles each retry).
BASE_BACKOFF_S = 1.0
#: Per-call network timeout (mirrors DataFetcher.CALL_TIMEOUT).
CALL_TIMEOUT = 30.0
#: Safety cap for history pagination loops (guards against endless paging).
MAX_HISTORY_PAGES = 100
#: OKX funding-rate-history single-page cap (endpoint max is 100; a larger
#: requested limit is rejected with 51000 "Parameter limit error").
FUNDING_HISTORY_PAGE_MAX = 100
#: OKX rubik OI-volume: the endpoint returns the full begin..end window
#: (1H ~= 720 rows) and ignores the limit for the response size, but ccxt
#: slices the parsed rows by the ``limit`` argument — request a generous
#: cap so the window is not truncated client-side.
OI_HISTORY_PAGE_MAX = 1000

FUNDING_HISTORY_COLUMNS = ["timestamp", "funding_rate", "realized_rate", "funding_time"]
OI_HISTORY_COLUMNS = ["timestamp", "open_interest", "open_interest_ccy", "open_interest_usd"]


class RateLimiter:
    """IP-level serial rate limiter (analyze locked decision: self-throttle).

    Guarantees at least ``min_interval`` seconds between the START of
    consecutive requests, independent of ccxt's internal throttling. One
    limiter instance is shared across all meta endpoints of a session.
    """

    def __init__(self, min_interval: float = MIN_ENDPOINT_INTERVAL_S) -> None:
        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last_request = 0.0  # monotonic timestamp of last granted slot

    @property
    def min_interval(self) -> float:
        return self._min_interval

    async def acquire(self) -> None:
        """Wait until the next request slot is available, then claim it."""
        async with self._lock:
            wait = self._last_request + self._min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()


@dataclass(frozen=True)
class FundingRateSnapshot:
    """One funding-rate sample from OKX /public/funding-rate."""

    symbol: str
    funding_rate: float
    sett_funding_rate: float
    sett_state: str
    funding_time: int
    next_funding_time: int
    fetched_at_ms: int

    @property
    def settlement_interval_ms(self) -> int:
        """Runtime-derived settlement period (D-lock C3: never hardcode 8h)."""
        return self.next_funding_time - self.funding_time


@dataclass(frozen=True)
class OpenInterestSnapshot:
    """One open-interest sample from OKX /public/open-interest (REST only)."""

    symbol: str
    open_interest: float
    open_interest_ccy: float
    open_interest_usd: float
    timestamp: int
    fetched_at_ms: int


def _to_float(value: Any, default: float = 0.0) -> float:
    """Coerce an exchange payload field to a finite float (fail to default)."""
    if value is None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _to_int(value: Any, default: int = 0) -> int:
    """Coerce an exchange payload field to int milliseconds."""
    if value is None:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _is_retryable(exc: Exception) -> bool:
    """True for OKX 50011 rate-limit responses and network-class errors."""
    if RATE_LIMIT_ERROR_CODE in str(exc):
        return True
    if isinstance(exc, (asyncio.TimeoutError, ConnectionError, OSError)):
        return True
    return isinstance(
        exc, (ccxt.RateLimitExceeded, ccxt.DDoSProtection, ccxt.NetworkError)
    )


class MarketMetaFetcher:
    """Fetch funding rates and open interest from OKX (REST).

    Args:
        config: DataConfig (sandbox flag + exchange identity).
        exchange: Optional shared ``ccxt.async_support.okx`` instance
            (M4-1.2 single-instance invariant — TradingSession injects the
            same instance DataFetcher uses). When None, the fetcher owns a
            private instance created by :meth:`connect`.
    """

    def __init__(self, config: DataConfig, exchange: Any | None = None) -> None:
        self._config = config
        self._exchange: Any | None = exchange
        self._owns_exchange = exchange is None
        # IP-level serial limiter shared by every endpoint of this fetcher.
        self._limiter = RateLimiter(MIN_ENDPOINT_INTERVAL_S)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Create the private exchange instance (no-op when one is injected)."""
        if self._exchange is not None:
            return
        try:
            # NOTE: no ccxt built-in throttling — this fetcher self-limits
            # via RateLimiter (analyze locked decision).
            exchange = ccxt.okx({"options": {"defaultType": "swap"}})
            if self._config.sandbox:
                exchange.set_sandbox_mode(True)
            await asyncio.wait_for(exchange.load_markets(), timeout=CALL_TIMEOUT)
            self._exchange = exchange
            logger.info("MarketMetaFetcher connected to OKX (meta endpoints)")
        except Exception as e:
            # Close the local instance on failure — otherwise the aiohttp
            # connector leaks (connect() raised before self._exchange was set).
            try:
                await exchange.close()
            except Exception:  # pragma: no cover - best-effort cleanup
                logger.debug("Meta fetcher close after connect failure", exc_info=True)
            raise GatewayConnectionError(f"Failed to connect meta fetcher: {e}") from e

    async def disconnect(self) -> None:
        """Close the exchange only if this fetcher owns it."""
        if self._exchange is not None and self._owns_exchange:
            try:
                await self._exchange.close()
            except Exception:  # pragma: no cover - teardown best-effort
                logger.debug("Meta fetcher close failed", exc_info=True)
        self._exchange = None

    def _require_exchange(self) -> Any:
        if self._exchange is None:
            raise GatewayConnectionError("Not connected. Call connect() first.")
        return self._exchange

    # ------------------------------------------------------------------
    # Retry plumbing
    # ------------------------------------------------------------------

    async def _retry_call(self, factory: Callable[[], Awaitable[Any]], op: str) -> Any:
        """Run an endpoint call with rate limiting and bounded retry.

        Retryable failures (50011 / network) back off 1 s -> 2 s -> 4 s with
        jitter, up to ``MAX_RETRIES`` retries; then raise ``DataError``
        (fail-closed — the caller decides the degraded posture).
        Non-retryable errors raise ``DataError`` immediately.
        """
        delay = BASE_BACKOFF_S
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                await self._limiter.acquire()
                return await asyncio.wait_for(factory(), timeout=CALL_TIMEOUT)
            except Exception as e:
                if not _is_retryable(e):
                    raise DataError(f"{op} failed: {e}") from e
                last_exc = e
                if attempt >= MAX_RETRIES:
                    break
                jitter = random.uniform(0.0, 0.1 * delay)  # noqa: S311
                logger.warning(
                    "%s retryable failure (%s); backoff %.2fs (attempt %d/%d)",
                    op,
                    e,
                    delay + jitter,
                    attempt + 1,
                    MAX_RETRIES,
                )
                await asyncio.sleep(delay + jitter)
                delay *= 2
        raise DataError(f"{op} failed after {MAX_RETRIES} retries: {last_exc}") from last_exc

    # ------------------------------------------------------------------
    # Funding rate
    # ------------------------------------------------------------------

    async def fetch_funding_rate(self, symbol: str) -> FundingRateSnapshot:
        """Fetch the current funding rate (ccxt /public/funding-rate)."""
        exchange = self._require_exchange()

        async def _call() -> Any:
            return await exchange.fetchFundingRate(symbol)

        raw: dict[str, Any] = await self._retry_call(_call, f"fetch_funding_rate({symbol})")
        info: dict[str, Any] = raw.get("info") or {}
        funding_time = _to_int(raw.get("fundingTimestamp") or info.get("fundingTime"))
        next_funding_time = _to_int(
            raw.get("nextFundingTimestamp") or info.get("nextFundingTime")
        )
        return FundingRateSnapshot(
            symbol=symbol,
            funding_rate=_to_float(raw.get("fundingRate") or info.get("fundingRate")),
            sett_funding_rate=_to_float(info.get("settFundingRate")),
            sett_state=str(info.get("settState") or ""),
            funding_time=funding_time,
            next_funding_time=next_funding_time,
            fetched_at_ms=int(time.time() * 1000),
        )

    async def fetch_funding_rate_history(
        self, symbol: str, since_ms: int, limit: int = 100
    ) -> pd.DataFrame:
        """Backfill funding-rate history with limit pagination.

        OKX only serves ~3 months of funding history (analyze C2 locked);
        callers truncate ``since_ms`` accordingly. Rows are de-duplicated by
        timestamp (incremental replay safe) and non-finite rates dropped.

        The page size is clamped to ``FUNDING_HISTORY_PAGE_MAX`` (100 — the
        endpoint's hard cap; larger values are rejected with OKX 51000).

        Returns:
            DataFrame[timestamp, funding_rate, realized_rate, funding_time],
            sorted by timestamp (ms int). Empty frame keeps the column
            contract.
        """
        exchange = self._require_exchange()
        rows: dict[int, dict[str, Any]] = {}
        since = int(since_ms)
        effective_limit = min(limit, FUNDING_HISTORY_PAGE_MAX)
        for _ in range(MAX_HISTORY_PAGES):
            page_since = since

            async def _call(s: int = page_since) -> Any:
                # fetchFundingRateHistory(symbol, since, limit, params) — the
                # limit argument must be an int, not a params dict (the old
                # spelling URL-encoded the dict into the limit query param,
                # which OKX rejects with 51000).
                return await exchange.fetchFundingRateHistory(
                    symbol, s, effective_limit, {}
                )

            page: list[dict[str, Any]] = await self._retry_call(
                _call, f"fetch_funding_rate_history({symbol})"
            )
            if not page:
                break
            last_ts = since
            for entry in page:
                ts = _to_int(entry.get("timestamp"), default=-1)
                if ts < 0:
                    continue
                info = entry.get("info") or {}
                rate = _to_float(entry.get("fundingRate") or info.get("fundingRate"), math.nan)
                realized = _to_float(info.get("realizedRate"), math.nan)
                # keep='last' semantics: a later page wins on duplicate ts.
                rows[ts] = {
                    "timestamp": ts,
                    "funding_rate": rate,
                    "realized_rate": realized if math.isfinite(realized) else rate,
                    "funding_time": _to_int(info.get("fundingTime"), default=ts),
                }
                last_ts = max(last_ts, ts)
            if len(page) < effective_limit:
                break
            since = last_ts + 1

        if not rows:
            return pd.DataFrame(columns=FUNDING_HISTORY_COLUMNS)
        df = pd.DataFrame(sorted(rows.values(), key=lambda r: r["timestamp"]))
        # Drop rows with non-finite funding rates (boundary hygiene).
        df = df[df["funding_rate"].apply(math.isfinite)]
        return df.reset_index(drop=True)

    # ------------------------------------------------------------------
    # Open interest (REST only — no WS support in ccxt pro)
    # ------------------------------------------------------------------

    async def fetch_open_interest(self, symbol: str) -> OpenInterestSnapshot:
        """Fetch current open interest (ccxt fetchOpenInterest, REST)."""
        exchange = self._require_exchange()

        async def _call() -> Any:
            return await exchange.fetchOpenInterest(symbol)

        raw: dict[str, Any] = await self._retry_call(_call, f"fetch_open_interest({symbol})")
        info: dict[str, Any] = raw.get("info") or {}
        fetched_at = int(time.time() * 1000)
        return OpenInterestSnapshot(
            symbol=symbol,
            open_interest=_to_float(raw.get("openInterest") or info.get("oi")),
            open_interest_ccy=_to_float(info.get("oiCcy")),
            open_interest_usd=_to_float(
                raw.get("openInterestValue") or info.get("oiUsd")
            ),
            timestamp=_to_int(raw.get("timestamp") or info.get("ts"), default=fetched_at),
            fetched_at_ms=fetched_at,
        )

    async def fetch_open_interest_history(
        self,
        symbol: str,
        period: str = "1H",
        since_ms: int = 0,
        limit: int = 100,
        end_ms: int | None = None,
    ) -> pd.DataFrame:
        """Backfill OI history via the OKX rubik contracts OI-volume endpoint.

        OKX requires the begin+end pair for this endpoint: begin-only or
        end-only requests are rejected with 50030 "Illegal time range"
        (verified against the live API). ccxt maps ``since`` -> ``begin`` and
        the ``until`` params entry -> ``end``, so a windowed fetch must pass
        both. The endpoint serves newest-first and caps coverage by period
        (observed: 1H ~= recent 30 days, 1D ~= 180 days); a requested window
        wider than the cap silently returns the accessible slice — the caller
        should check the returned row span rather than assume full coverage.

        Returns:
            DataFrame[timestamp, open_interest, open_interest_ccy,
            open_interest_usd] sorted by timestamp (ms int, ascending).
            Empty frame keeps the column contract.
        """
        exchange = self._require_exchange()
        rows: dict[int, dict[str, Any]] = {}
        window_start = int(since_ms) if since_ms and since_ms > 0 else None
        window_end = int(end_ms) if end_ms else int(time.time() * 1000)
        effective_limit = max(limit, OI_HISTORY_PAGE_MAX)

        async def _call() -> Any:
            params: dict[str, Any] = {"until": window_end} if window_start is not None else {}
            return await exchange.fetchOpenInterestHistory(
                symbol, period, window_start, effective_limit, params
            )

        page: list[dict[str, Any]] = await self._retry_call(
            _call, f"fetch_open_interest_history({symbol})"
        )
        for entry in page:
            ts = _to_int(entry.get("timestamp"), default=-1)
            if ts < 0:
                continue
            # ccxt rubik contracts OI-volume entries: the value lives in
            # ``openInterestValue`` (USD); ``openInterestAmount`` (coin) is
            # unset for contracts, and ``info`` is a raw LIST (no .get).
            oi_amount = _to_float(entry.get("openInterestAmount"), math.nan)
            if not math.isfinite(oi_amount):
                oi_amount = _to_float(entry.get("openInterest"), math.nan)
            oi_value = _to_float(entry.get("openInterestValue"), math.nan)
            rows[ts] = {
                "timestamp": ts,
                "open_interest": oi_value if math.isfinite(oi_value) else oi_amount,
                "open_interest_ccy": oi_amount,
                "open_interest_usd": oi_value,
            }

        if not rows:
            return pd.DataFrame(columns=OI_HISTORY_COLUMNS)
        df = pd.DataFrame(sorted(rows.values(), key=lambda r: r["timestamp"]))
        df = df[df["open_interest"].apply(math.isfinite)]
        df = df.reset_index(drop=True)
        if window_start is not None and len(df) and int(df["timestamp"].min()) > window_start:
            logger.warning(
                "OI coverage for %s %s starts at %d (requested %d) — OKX period "
                "cap (1H ~= 30d, 1D ~= 180d)",
                symbol,
                period,
                int(df["timestamp"].min()),
                window_start,
            )
        return df


# ---------------------------------------------------------------------------
# Freshness gates (fail-closed; consumed by T-s2-04 live guard)
# ---------------------------------------------------------------------------


def is_funding_fresh(
    snapshot: FundingRateSnapshot | None,
    now_ms: int,
    settlement_interval_ms: int,
) -> bool:
    """Fail-closed funding freshness: age <= FUNDING_MAX_AGE_FACTOR x interval.

    Any unknown (missing snapshot, non-positive interval, negative age) is
    judged STALE so downstream entry gates block new positions.
    """
    if snapshot is None or settlement_interval_ms <= 0:
        return False
    age_ms = now_ms - snapshot.fetched_at_ms
    if age_ms < 0:
        return False
    return age_ms <= FUNDING_MAX_AGE_FACTOR * settlement_interval_ms


def is_oi_fresh(snapshot: OpenInterestSnapshot | None, now_ms: int) -> bool:
    """Fail-closed OI freshness: age <= OI_MAX_AGE_S (REST-only feed)."""
    if snapshot is None:
        return False
    age_ms = now_ms - snapshot.fetched_at_ms
    if age_ms < 0:
        return False
    return age_ms <= OI_MAX_AGE_S * 1000
