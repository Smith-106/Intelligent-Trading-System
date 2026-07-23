"""CCXT-based data fetcher for Crypto market data.

Supports both REST API polling and WebSocket streaming for real-time data.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import ccxt.async_support as ccxt
import duckdb
import pandas as pd

from quantflow.common.config import DataConfig
from quantflow.common.exceptions import DataError, GatewayConnectionError
from quantflow.common.validators import validate_symbol

logger = logging.getLogger(__name__)

TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]

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

        all_bars: list[list[Any]] = []
        while True:
            bars = await asyncio.wait_for(
                self._exchange.fetch_ohlcv(
                    symbol,
                    timeframe,
                    since=since,
                    limit=limit,
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
            if end:
                end_ts = self._exchange.parse8601(f"{end}T23:59:59Z")
                if last_ts >= end_ts:
                    all_bars = [b for b in all_bars if b[0] <= end_ts]
                    break
            since = last_ts + 1
            if len(bars) < limit:
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

    async def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        """Fetch current ticker for a symbol."""
        if not self._exchange:
            raise GatewayConnectionError("Not connected")
        return cast(
            dict[str, Any],
            await asyncio.wait_for(self._exchange.fetch_ticker(symbol), timeout=CALL_TIMEOUT),
        )

    def get_last_timestamp(self, symbol: str, timeframe: str, parquet_dir: Path) -> int | None:
        """Get the last stored timestamp for incremental updates.

        SECURITY: validate symbol + timeframe before SQL interpolation. The
        f-string previously embedded raw symbol/timeframe into a DuckDB
        read_parquet query, allowing SQL injection if either was attacker-
        controlled. Even though this is currently uncalled (dead code), fix
        it so a future caller is safe by construction.

        NOTE (REV-007): this re-implements DataStore's read path against
        DataStore's on-disk layout. A future refactor should delegate to
        ``DataStore.get_date_range`` (the layer-correct owner of parquet
        reads) rather than hand-rolling a DuckDB query here.
        """
        symbol_name = validate_symbol(symbol)
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"Invalid timeframe: {timeframe!r}. Allowed: {TIMEFRAMES}")

        # .as_posix() keeps the glob forward-slash on Windows (mirrors
        # store.py:155 / feature_store.py); escape single quotes so a
        # parquet_dir containing a quote cannot break the glob literal.
        pattern = f"{parquet_dir.as_posix()}/{symbol_name}/*/*/*.parquet".replace("'", "''")
        try:
            result = duckdb.query(
                f"""
                SELECT MAX(timestamp) as max_ts
                FROM read_parquet('{pattern}')
                WHERE timeframe = ?
                """,
                params=[timeframe],
            ).fetchone()
            return result[0] if result and result[0] is not None else None
        except Exception as e:
            logger.warning("get_last_timestamp failed for %s %s: %s", symbol, timeframe, e)
            return None

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
