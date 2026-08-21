"""CCXT-based data fetcher for Crypto market data.

Supports both REST API polling and WebSocket streaming for real-time data.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import ccxt.async_support as ccxt
import pandas as pd

from quantflow.common.config import DataConfig
from quantflow.common.exceptions import DataError, GatewayConnectionError

logger = logging.getLogger(__name__)

# OKX-native intervals used by download / store / live. 10m is intentionally
# absent (exchange has no native 10m kline). 3m/1w/1M included for completeness.
TIMEFRAMES = [
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
]

# OKX kline API caps a single response at 300 bars regardless of the limit
# param (ccxt truncates silently). Pagination must compare against this page
# size, not the caller's limit.
OKX_KLINE_PAGE_MAX = 300

# Safety cap on pagination loops (defensive; 500 pages ≈ 150k bars per call
# at the OKX page size — far beyond any realistic date window).
MAX_PAGINATION_PAGES = 500

# Per-call timeout for every CCXT network call (odyssey-improve GP2).
# A bare ``await exchange.<method>`` has no timeout floor, so a TCP stall /
# network partition hangs the data loop indefinitely — the same unbounded-hang
# class fixed in okx_gateway. load_markets / fetch_ohlcv / fetch_ticker / ws
# watch / close are all bounded by this value.
CALL_TIMEOUT = 30.0


def _bar_is_finite(bar: list[Any]) -> bool:
    """Return True if every numeric OHLCV field of a CCXT bar is finite.

    A CCXT bar is ``[timestamp, open, high, low, close, volume]``. The
    timestamp must be a non-null int and each price/volume must be a finite
    float (odyssey-improve GP3) — null/NaN/inf values from a partial kline
    are rejected at the parse boundary instead of propagating downstream.
    """
    if len(bar) < 6:
        return False
    try:
        for field in (bar[1], bar[2], bar[3], bar[4], bar[5]):
            if field is None or not math.isfinite(float(field)):
                return False
    except (TypeError, ValueError):
        return False
    return True


class DataFetcher:
    """Fetches historical and real-time data from OKX via CCXT.

    For real-time data, supports WebSocket streaming via the watch_ methods
    (CCXT pro) or polling fallback.

    .. invariant:: **Single instance per session** (M4-1.2)

       A TradingSession MUST create exactly ONE DataFetcher (and thus one
       underlying ``ccxt.okx`` exchange instance) shared across all symbols.
       CCXT's built-in rate-limit throttler is per-instance; multiple
       DataFetcher instances would each run an independent throttler,
       causing uncoordinated concurrent requests that trigger OKX HTTP 429
       rate-limit rejections. The multi-symbol data loop (M4-4) rotates a
       single poller over all symbols through this shared instance.
    """

    def __init__(self, config: DataConfig) -> None:
        self._config = config
        self._exchange: ccxt.okx | None = None
        self._ws_running = False
        self._ws_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        try:
            self._exchange = ccxt.okx(
                {
                    "enableRateLimit": True,
                    "rateLimit": 1000 / self._config.rate_limit,
                    "options": {"defaultType": "spot"},
                }
            )
            if self._config.sandbox:
                self._exchange.set_sandbox_mode(True)
            await asyncio.wait_for(self._exchange.load_markets(), timeout=CALL_TIMEOUT)
            logger.info("Connected to OKX, %d markets loaded", len(self._exchange.markets))
        except Exception as e:
            if self._exchange is not None:
                try:
                    await self._exchange.close()
                except Exception:
                    logger.debug("Failed to close exchange after connection error", exc_info=True)
                finally:
                    self._exchange = None
            raise GatewayConnectionError(f"Failed to connect to OKX: {e}") from e

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        start: str | None = None,
        end: str | None = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """Fetch OHLCV kline data."""
        if not self._exchange:
            raise GatewayConnectionError("Not connected. Call connect() first.")
        if timeframe not in TIMEFRAMES:
            raise DataError(f"Invalid timeframe: {timeframe}. Valid: {TIMEFRAMES}")

        since = None
        if start:
            since = self._exchange.parse8601(f"{start}T00:00:00Z")

        # OKX kline API caps a single response at 300 bars regardless of the
        # requested limit; ccxt silently truncates. The page-full test must
        # therefore use the EXCHANGE page size, not the requested limit —
        # otherwise a 300-bar page is mistaken for the last page and the
        # loop exits after one fetch (only 300 bars downloaded).
        effective_limit = min(limit, OKX_KLINE_PAGE_MAX)
        end_ts = self._exchange.parse8601(f"{end}T23:59:59Z") if end else None

        all_bars: list[list[Any]] = []
        pages = 0
        while True:
            pages += 1
            if pages > MAX_PAGINATION_PAGES:
                # RV-012: a silent stop here truncated history while callers
                # treated the result as complete — raise instead.
                raise DataError(f"Pagination exceeded {MAX_PAGINATION_PAGES} pages for {symbol}")
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
            # Reject non-finite OHLCV at the parse boundary (odyssey-improve GP3).
            # A malformed OKX response (null/NaN/inf from a partial kline) would
            # otherwise flow straight into store.save → cleaner → backtest/live
            # bars; cleaner fills NaN gaps but does NOT reject non-finite values.
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
                # end-date window not yet covered: keep paginating even when
                # the page is short (OKX may return fewer bars than the page
                # cap in a partial window, but more pages may still exist).
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
        logger.info("Fetched %d bars for %s/%s", len(df), symbol, timeframe)
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
        """Fetch many symbols over the shared single ccxt instance.

        ``max_concurrency=1`` keeps the per-instance rate limiter authoritative
        (M4-1.2 invariant) and is the default — values >1 are gated on
        ``scripts/verify_okx_throttler.py --concurrency N`` returning zero 429s.
        A failing symbol is reported via ``on_symbol_error`` and omitted from
        the result rather than aborting the batch (P5-F5 exit-code contract).
        """
        sem = asyncio.Semaphore(max_concurrency)

        async def _one(sym: str) -> pd.DataFrame | None:
            async with sem:
                try:
                    return await self.fetch_ohlcv(sym, timeframe, start, end)
                except Exception as e:
                    logger.warning("OKX fetch failed for %s: %s", sym, e)
                    if on_symbol_error:
                        on_symbol_error(sym, e)
                    return None

        results = await asyncio.gather(*[_one(s) for s in symbols])
        return {
            sym: df
            for sym, df in zip(symbols, results, strict=True)
            if df is not None and not df.empty
        }

    async def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        """Fetch current ticker for a symbol."""
        if not self._exchange:
            raise GatewayConnectionError("Not connected")
        return cast(
            dict[str, Any],
            await asyncio.wait_for(self._exchange.fetch_ticker(symbol), timeout=CALL_TIMEOUT),
        )

    async def fetch_trades(
        self,
        symbol: str,
        *,
        since: int | None = None,
        limit: int = 100,
    ) -> pd.DataFrame:
        """W21c: fetch recent public trades (scaffold for true CVD).

        Returns DataFrame columns: timestamp, price, amount, side.
        Empty frame when exchange unavailable or no trades — callers should
        fail closed to ``cvd_proxy`` rather than inventing aggressor flags.
        """
        if not self._exchange:
            raise GatewayConnectionError("Not connected")
        raw = await asyncio.wait_for(
            self._exchange.fetch_trades(symbol, since=since, limit=limit),
            timeout=CALL_TIMEOUT,
        )
        if not raw:
            return pd.DataFrame(columns=["timestamp", "price", "amount", "side"])
        rows: list[dict[str, Any]] = []
        for t in raw:
            if not isinstance(t, dict):
                continue
            rows.append(
                {
                    "timestamp": int(t.get("timestamp") or 0),
                    "price": float(t.get("price") or 0.0),
                    "amount": float(t.get("amount") or 0.0),
                    "side": str(t.get("side") or ""),
                }
            )
        if not rows:
            return pd.DataFrame(columns=["timestamp", "price", "amount", "side"])
        return pd.DataFrame(rows)

    async def watch_trades(
        self,
        symbol: str,
        callback: Callable[[pd.DataFrame], Any] | None = None,
        *,
        limit: int = 50,
        poll_fallback_interval_s: float = 5.0,
    ) -> None:
        """W24c: stream public trades via ccxt.pro ``watch_trades`` when available.

        Falls back to REST ``fetch_trades`` polling when WS is missing. Stops when
        ``stop_stream()`` is called (shares ``_ws_running`` with bar streams — only
        one active stream per DataFetcher instance).

        Callback receives a DataFrame with columns timestamp/price/amount/side.
        """
        if not self._exchange:
            raise GatewayConnectionError("Not connected")
        self.stop_stream()
        self._ws_running = True
        self._ws_task = asyncio.ensure_future(
            self._watch_trades_loop(
                symbol,
                callback,
                limit=limit,
                poll_fallback_interval_s=poll_fallback_interval_s,
            )
        )

    async def _watch_trades_loop(
        self,
        symbol: str,
        callback: Callable[[pd.DataFrame], Any] | None,
        *,
        limit: int,
        poll_fallback_interval_s: float,
    ) -> None:
        exchange = self._exchange
        if exchange is None:
            return
        use_ws = hasattr(exchange, "watch_trades")
        if not use_ws:
            logger.info(
                "watch_trades: no ccxt.pro watch_trades — REST poll fallback (%.1fs)",
                poll_fallback_interval_s,
            )
        try:
            while self._ws_running:
                try:
                    if use_ws:
                        raw = await asyncio.wait_for(
                            exchange.watch_trades(symbol), timeout=CALL_TIMEOUT
                        )
                    else:
                        raw = await asyncio.wait_for(
                            exchange.fetch_trades(symbol, limit=limit),
                            timeout=CALL_TIMEOUT,
                        )
                        await asyncio.sleep(max(1.0, float(poll_fallback_interval_s)))
                except Exception as e:
                    logger.warning("watch_trades error: %s — retry", e)
                    await asyncio.sleep(2.0)
                    continue
                if not raw:
                    continue
                rows: list[dict[str, Any]] = []
                for t in raw if isinstance(raw, list) else [raw]:
                    if not isinstance(t, dict):
                        continue
                    rows.append(
                        {
                            "timestamp": int(t.get("timestamp") or 0),
                            "price": float(t.get("price") or 0.0),
                            "amount": float(t.get("amount") or 0.0),
                            "side": str(t.get("side") or ""),
                        }
                    )
                if not rows:
                    continue
                frame = pd.DataFrame(rows)
                if callback is not None:
                    result = callback(frame)
                    if inspect.isawaitable(result):
                        await result
        except asyncio.CancelledError:
            logger.info("watch_trades loop cancelled")
            raise
        finally:
            self._ws_running = False

    def get_last_timestamp(self, symbol: str, timeframe: str, parquet_dir: Path) -> int | None:
        """Get the last stored timestamp for incremental updates.

        ISS-027: delegates to ``DataStore.get_last_timestamp`` — the layer-
        correct owner of parquet reads — instead of hand-rolling a duplicate
        DuckDB ``read_parquet`` glob query here. The prior copy diverged from
        DataStore's read path (different glob depth, separate symbol
        validation), a drift risk now eliminated by single-ownership. Symbol
        + timeframe validation move into DataStore so a future caller is safe
        by construction (this method is currently uncalled but kept as the
        public fetcher entry point for incremental-update callers).
        """
        from quantflow.data.store import DataStore

        store = DataStore(str(parquet_dir))
        try:
            return store.get_last_timestamp(symbol, timeframe)
        finally:
            store.close()

    async def disconnect(self) -> None:
        self.stop_stream()
        if self._exchange:
            await asyncio.wait_for(self._exchange.close(), timeout=CALL_TIMEOUT)
            self._exchange = None
            logger.info("Disconnected from OKX")

    # --- WebSocket / Streaming ---

    async def stream_bars(
        self,
        symbol: str,
        timeframe: str = "1m",
        callback: Callable[[dict[str, Any]], None] | None = None,
        poll_interval: float = 1.0,
    ) -> None:
        """Stream real-time bar data via polling.

        Uses REST polling as a universal fallback. If CCXT pro is installed
        and the exchange supports watch_ohlcv, it will be used instead.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            timeframe: Candle interval.
            callback: Called with each new bar dict: {timestamp, open, high,
                      low, close, volume, symbol, timeframe}.
            poll_interval: Seconds between polls (REST fallback only).
        """
        if not self._exchange:
            raise GatewayConnectionError("Not connected. Call connect() first.")

        self._ws_running = True
        logger.info("Starting bar stream for %s/%s", symbol, timeframe)

        # Try WebSocket (CCXT pro) first
        if hasattr(self._exchange, "watch_ohlcv"):
            self._ws_task = asyncio.ensure_future(self._stream_ws(symbol, timeframe, callback))
        else:
            self._ws_task = asyncio.ensure_future(
                self._stream_poll(symbol, timeframe, callback, poll_interval)
            )

    async def _stream_ws(
        self,
        symbol: str,
        timeframe: str,
        callback: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        """Stream via CCXT pro watch_ohlcv (WebSocket)."""
        exchange = self._exchange
        if exchange is None:
            raise GatewayConnectionError("Not connected. Call connect() first.")
        last_ts = 0
        while self._ws_running:
            try:
                bars = await asyncio.wait_for(
                    exchange.watch_ohlcv(symbol, timeframe), timeout=CALL_TIMEOUT
                )
                for bar in bars:
                    if not _bar_is_finite(bar):
                        continue
                    ts = bar[0]
                    if ts > last_ts:
                        last_ts = ts
                        bar_dict: dict[str, Any] = {
                            "timestamp": ts,
                            "open": bar[1],
                            "high": bar[2],
                            "low": bar[3],
                            "close": bar[4],
                            "volume": bar[5],
                            "symbol": symbol,
                            "timeframe": timeframe,
                        }
                        if callback:
                            callback(bar_dict)
            except Exception as e:
                logger.warning("WebSocket stream error: %s, retrying...", e)
                await asyncio.sleep(1)

    async def _stream_poll(
        self,
        symbol: str,
        timeframe: str,
        callback: Callable[[dict[str, Any]], None] | None,
        poll_interval: float,
    ) -> None:
        """Stream via REST polling fallback."""
        exchange = self._exchange
        if exchange is None:
            raise GatewayConnectionError("Not connected. Call connect() first.")
        last_ts = 0
        while self._ws_running:
            try:
                bars = await asyncio.wait_for(
                    exchange.fetch_ohlcv(symbol, timeframe, limit=1), timeout=CALL_TIMEOUT
                )
                if bars:
                    bar = bars[-1]
                    if not _bar_is_finite(bar):
                        bar = None
                else:
                    bar = None
                if bar is not None:
                    ts = bar[0]
                    if ts > last_ts:
                        last_ts = ts
                        bar_dict: dict[str, Any] = {
                            "timestamp": ts,
                            "open": bar[1],
                            "high": bar[2],
                            "low": bar[3],
                            "close": bar[4],
                            "volume": bar[5],
                            "symbol": symbol,
                            "timeframe": timeframe,
                        }
                        if callback:
                            callback(bar_dict)
            except Exception as e:
                logger.warning("Poll stream error: %s", e)
            await asyncio.sleep(poll_interval)

    def stop_stream(self) -> None:
        """Stop the active bar stream."""
        self._ws_running = False
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
        self._ws_task = None
        logger.info("Bar stream stopped")

    async def watch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        callback: Any,
    ) -> None:
        """Subscribe to real-time OHLCV candles via WebSocket.

        Proxies to the underlying ``ccxt.okx.watch_ohlcv`` when ccxt.pro is
        installed.  Falls back to a warning + no-op when the pro extension is
        absent so callers can issue the call unconditionally.

        This is a *fire-and-forget* subscribe: the watch loop is spawned as
        an asyncio task managed by :pyattr:`_ws_task` (shared with
        ``stream_bars`` — only one active stream per DataFetcher instance).

        Args:
            symbol: Trading pair (e.g. ``"BTC/USDT"``).
            timeframe: Candle interval (e.g. ``"1m"``).
            callback: Invoked with each new list of OHLCV bars.
        """
        if self._exchange is None:
            logger.warning("No exchange connected — watch_ohlcv is no-op")
            return
        if not hasattr(self._exchange, "watch_ohlcv"):
            logger.warning(
                "ccxt.pro not available — watch_ohlcv('%s', '%s') is no-op",
                symbol,
                timeframe,
            )
            return

        self._ws_running = True
        self._ws_task = asyncio.ensure_future(self._watch_ohlcv_raw(symbol, timeframe, callback))

    async def _watch_ohlcv_raw(
        self,
        symbol: str,
        timeframe: str,
        callback: Any,
    ) -> None:
        """Raw watch loop that forwards ccxt OHLCV lists to *callback*.

        Unlike ``_stream_ws`` (which wraps each bar in a dict for the
        DataFetcher stream API), this loop passes the raw ``[[ts, o, h, l,
        c, v], …]`` list straight through — matching the gateway-level
        ``subscribe('ohlcv', …)`` contract.
        """
        exchange = self._exchange
        if exchange is None:
            return
        backoff = 1.0
        while self._ws_running:
            try:
                ohlcv = await asyncio.wait_for(
                    exchange.watch_ohlcv(symbol, timeframe), timeout=CALL_TIMEOUT
                )
                if ohlcv and callback:
                    if inspect.iscoroutinefunction(callback):
                        await callback(ohlcv)
                    else:
                        callback(ohlcv)
                backoff = 1.0
                await asyncio.sleep(0)  # Yield to event loop
            except Exception as e:
                logger.warning(
                    "watch_ohlcv error: %s, reconnecting in %.0fs",
                    type(e).__name__,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 16.0)
