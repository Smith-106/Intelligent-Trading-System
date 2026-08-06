"""Download real spot+perp dataset for spot_perp_arb validation (ISS-20260804-003).

Fetches a ~90-day window (OKX funding-history cap) of:
  * BTC perp (BTC-USDT-SWAP) 1h klines   -> store symbol "BTC-USDT-SWAP"
  * BTC perp funding-rate history         -> meta_funding_rate/BTC-USDT-SWAP
  * BTC perp open-interest history (1H)   -> meta_open_interest/BTC-USDT-SWAP

Spot klines (BTC_USDT) are downloaded separately via the CLI:
  quantflow download --symbol BTC/USDT --timeframe 1h --start <start> --end <end>

The perp klines page with the fixed fetcher pagination contract
(effective_limit=min(limit,300), end-guard, MAX_PAGINATION_PAGES).
"""

from __future__ import annotations

import asyncio
import logging
import math
import sys
import time
from pathlib import Path

import ccxt.async_support as ccxt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantflow.common.config import load_config
from quantflow.data.market_meta_fetcher import MarketMetaFetcher
from quantflow.data.store import DataStore

logger = logging.getLogger("download_spot_perp_data")

PERP_SYMBOL_STORE = "BTC-USDT-SWAP"
PERP_SYMBOL_CCXT = "BTC/USDT:USDT"
TIMEFRAME = "1h"
WINDOW_DAYS = 90
OKX_KLINE_PAGE_MAX = 300
MAX_PAGINATION_PAGES = 500
CALL_TIMEOUT_S = 45
OUTER_RETRIES = 5
OUTER_BACKOFF_S = 12


async def _fetch_perp_klines(
    exchange: ccxt.okx, since_ms: int, end_ms: int, limit: int = 1000
) -> list[list[float]]:
    """Paginated 1h klines from ``since_ms`` through ``end_ms`` (end-guard)."""
    effective_limit = min(limit, OKX_KLINE_PAGE_MAX)
    since = since_ms
    all_bars: list[list[float]] = []
    pages = 0
    while True:
        pages += 1
        if pages > MAX_PAGINATION_PAGES:
            logger.warning("Pagination exceeded %d pages; stopping", MAX_PAGINATION_PAGES)
            break
        bars = await asyncio.wait_for(
            exchange.fetch_ohlcv(PERP_SYMBOL_CCXT, TIMEFRAME, since=since, limit=effective_limit),
            timeout=CALL_TIMEOUT_S,
        )
        if not bars:
            break
        bars = [b for b in bars if all(math.isfinite(float(v)) for v in b)]
        if not bars:
            break
        all_bars.extend(bars)
        last_ts = bars[-1][0]
        if last_ts >= end_ms:
            all_bars = [b for b in all_bars if b[0] <= end_ms]
            break
        since = last_ts + 1

    # De-dup + sort by timestamp.
    seen: dict[int, list[float]] = {}
    for b in all_bars:
        seen[int(b[0])] = b
    return [seen[k] for k in sorted(seen)]


async def _run_once(cfg, store: DataStore) -> None:
    # --- perp klines (dedicated swap exchange) ---
    swap = ccxt.okx({"options": {"defaultType": "swap"}})
    try:
        await swap.load_markets()
        now_ms = int(time.time() * 1000)
        since_ms = now_ms - WINDOW_DAYS * 86_400_000
        bars = await _fetch_perp_klines(swap, since_ms, now_ms)
        if not bars:
            raise RuntimeError("No perp klines fetched")
        import pandas as pd

        df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["symbol"] = PERP_SYMBOL_STORE
        df["timeframe"] = TIMEFRAME
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = (
            df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        )
        store.save(df, PERP_SYMBOL_STORE)
        print(f"✓ perp klines: {len(df)} bars ({PERP_SYMBOL_STORE} 1h)")
    finally:
        await swap.close()

    # --- funding + OI via MarketMetaFetcher (own limiter + retry) ---
    meta = MarketMetaFetcher(cfg.data)
    try:
        await meta.connect()
        since_ms = int(time.time() * 1000) - WINDOW_DAYS * 86_400_000
        funding = await meta.fetch_funding_rate_history(PERP_SYMBOL_CCXT, since_ms)
        if funding.empty:
            raise RuntimeError("No funding history fetched")
        store.save_funding_rates(funding, PERP_SYMBOL_STORE)
        print(f"✓ funding history: {len(funding)} rows ({PERP_SYMBOL_STORE})")

        oi = await meta.fetch_open_interest_history(
            PERP_SYMBOL_CCXT, period="1H", since_ms=since_ms
        )
        if oi.empty:
            raise RuntimeError("No OI history fetched")
        store.save_open_interest(oi, PERP_SYMBOL_STORE)
        print(f"✓ OI history: {len(oi)} rows ({PERP_SYMBOL_STORE})")
    finally:
        await meta.disconnect()


def main() -> None:
    cfg = load_config("quantflow/config/default.yaml")
    store = DataStore(cfg.data.parquet_dir, cfg.data.duckdb_path)
    try:
        last_err: Exception | None = None
        for attempt in range(1, OUTER_RETRIES + 1):
            try:
                asyncio.run(_run_once(cfg, store))
                return
            except Exception as e:
                last_err = e
                print(f"✗ attempt {attempt}/{OUTER_RETRIES} failed: {e}")
                if attempt < OUTER_RETRIES:
                    time.sleep(OUTER_BACKOFF_S)
        raise SystemExit(f"All {OUTER_RETRIES} attempts failed: {last_err}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
