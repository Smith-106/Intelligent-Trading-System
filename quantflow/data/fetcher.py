"""CCXT-based data fetcher for Crypto market data.

Supports both REST API polling and WebSocket streaming for real-time data.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import ccxt.async_support as ccxt
import pandas as pd

from quantflow.common.config import DataConfig
from quantflow.common.exceptions import DataError, GatewayConnectionError

logger = logging.getLogger(__name__)

TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]


class DataFetcher:
    """Fetches historical and real-time data from OKX via CCXT.

    For real-time data, supports WebSocket streaming via the watch_ methods
    (CCXT pro) or polling fallback.
    """

    def __init__(self, config: DataConfig) -> None:
        self._config = config
        self._exchange: ccxt.okx | None = None
        self._ws_running = False
        self._ws_task: asyncio.Task | None = None

    async def connect(self) -> None:
        try:
            self._exchange = ccxt.okx({
                "enableRateLimit": True,
                "rateLimit": 1000 / self._config.rate_limit,
                "options": {"defaultType": "spot"},
            })
            if self._config.sandbox:
                self._exchange.set_sandbox_mode(True)
            await self._exchange.load_markets()
            logger.info("Connected to OKX, %d markets loaded", len(self._exchange.markets))
        except Exception as e:
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

        all_bars: list[list] = []
        while True:
            bars = await self._exchange.fetch_ohlcv(
                symbol, timeframe, since=since, limit=limit,
            )
            if not bars:
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
        df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        logger.info("Fetched %d bars for %s/%s", len(df), symbol, timeframe)
        return df

    async def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        """Fetch current ticker for a symbol."""
        if not self._exchange:
            raise GatewayConnectionError("Not connected")
        return await self._exchange.fetch_ticker(symbol)

    def get_last_timestamp(self, symbol: str, timeframe: str, parquet_dir: Path) -> int | None:
        """Get the last stored timestamp for incremental updates."""
        import duckdb

        pattern = f"{parquet_dir}/{symbol.replace('/', '_')}/*/*/*.parquet"
        try:
            result = duckdb.query(f"""
                SELECT MAX(timestamp) as max_ts
                FROM read_parquet('{pattern}')
                WHERE timeframe = '{timeframe}'
            """).fetchone()
            return result[0] if result and result[0] else None
        except Exception:
            return None

    async def disconnect(self) -> None:
        await self.stop_stream()
        if self._exchange:
            await self._exchange.close()
            self._exchange = None
            logger.info("Disconnected from OKX")

    # --- WebSocket / Streaming ---

    async def stream_bars(
        self,
        symbol: str,
        timeframe: str = "1m",
        callback: Callable[[dict], None] | None = None,
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
            self._ws_task = asyncio.ensure_future(
                self._stream_ws(symbol, timeframe, callback)
            )
        else:
            self._ws_task = asyncio.ensure_future(
                self._stream_poll(symbol, timeframe, callback, poll_interval)
            )

    async def _stream_ws(
        self,
        symbol: str,
        timeframe: str,
        callback: Callable[[dict], None] | None,
    ) -> None:
        """Stream via CCXT pro watch_ohlcv (WebSocket)."""
        last_ts = 0
        while self._ws_running:
            try:
                bars = await self._exchange.watch_ohlcv(symbol, timeframe)
                for bar in bars:
                    ts = bar[0]
                    if ts > last_ts:
                        last_ts = ts
                        bar_dict = {
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
        callback: Callable[[dict], None] | None,
        poll_interval: float,
    ) -> None:
        """Stream via REST polling fallback."""
        last_ts = 0
        while self._ws_running:
            try:
                bars = await self._exchange.fetch_ohlcv(symbol, timeframe, limit=1)
                if bars:
                    bar = bars[-1]
                    ts = bar[0]
                    if ts > last_ts:
                        last_ts = ts
                        bar_dict = {
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
