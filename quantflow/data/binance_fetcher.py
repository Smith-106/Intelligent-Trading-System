"""Binance public-data archive fetcher.

Downloads historical klines / funding rates from ``data.binance.vision``
(the free, no-auth, no-rate-limit public archive) and returns DataFrames
with the same column contract as the OKX ``DataFetcher`` so the shared
``clean_ohlcv`` → ``DataStore.save`` pipeline can ingest them unchanged.

Layout (verified 2026-08):
    https://data.binance.vision/data/spot/monthly/klines/{SYMBOL}/{interval}/{SYMBOL}-{interval}-{YYYY}-{MM}.zip
    https://data.binance.vision/data/futures/um/monthly/klines/{SYMBOL}/{interval}/...
    https://data.binance.vision/data/futures/um/monthly/fundingRate/{SYMBOL}/...

Kline CSV rows are 12 fields: openTime, open, high, low, close, volume,
closeTime, quoteVolume, tradeCount, takerBuyBase, takerBuyQuote, ignore.
"""

from __future__ import annotations

import io
import logging
import urllib.error
import urllib.request
import zipfile
from typing import Any

import pandas as pd

from quantflow.common.exceptions import DataError

logger = logging.getLogger(__name__)

BINANCE_ARCHIVE_BASE = "https://data.binance.vision/data"

# Binance archive intervals (subset shared with QuantFlow TIMEFRAMES).
BINANCE_INTERVALS = (
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
)

# Network timeout for a single archive download (large monthly 1m zips can be
# tens of MB; keep generous but bounded).
DOWNLOAD_TIMEOUT = 120.0

# Column order the OKX fetcher returns; Binance ingests through the same shape.
KLINE_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

# Binance 12-field CSV header (openTime is ms epoch).
_BINANCE_KLINE_HEADER = [
    "openTime",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "closeTime",
    "quoteVolume",
    "tradeCount",
    "takerBuyBase",
    "takerBuyQuote",
    "ignore",
]


def _to_binance_symbol(symbol: str) -> str:
    """Map a QuantFlow symbol (``BTC/USDT``) to the Binance archive form (``BTCUSDT``).

    Accepts either form; validates no path separators survive (REV-008 style
    write-path hygiene, archive URLs are user-constructible here).
    """
    cleaned = symbol.replace("/", "").upper()
    if not cleaned.isalnum():
        raise DataError(f"Invalid symbol for Binance archive: {symbol!r}")
    return cleaned


def _normalize_epoch_ms(values: Any) -> Any:
    """Coerce Binance archive epoch values to milliseconds.

    Binance switched monthly kline archives from millisecond to microsecond
    ``openTime`` in newer files (observed 2026-08: recent months ship 16-digit
    microsecond stamps while pre-2025 files stay 13-digit ms). Detect by
    magnitude — anything >= 1e14 is microseconds (1e14 ms ≈ year 5138, no
    legitimate ms stamp is that large).
    """
    v = values.astype("int64")
    return v.where(v < 100_000_000_000_000, v // 1000)


class BinanceArchiveFetcher:
    """Download Binance public-archive history into QuantFlow-shaped frames.

    Pure file download (no API key, no rate limit) — synchronous by design;
    unlike the OKX ``DataFetcher`` there is no connection lifecycle.
    """

    def __init__(self, timeout: float = DOWNLOAD_TIMEOUT) -> None:
        self._timeout = timeout

    # ------------------------------------------------------------------
    # klines
    # ------------------------------------------------------------------

    def fetch_monthly_klines(
        self,
        symbol: str,
        timeframe: str,
        year: int,
        month: int,
        *,
        market: str = "spot",
    ) -> pd.DataFrame:
        """Fetch one calendar month of klines from the Binance archive.

        market: "spot" or "futures" (futures uses the U-margined monthly
        layout ``futures/um/monthly/klines``).
        """
        if timeframe not in BINANCE_INTERVALS:
            raise DataError(
                f"Invalid Binance interval {timeframe!r}. Valid: {sorted(BINANCE_INTERVALS)}"
            )
        bsym = _to_binance_symbol(symbol)
        url = self._archive_url(market, "klines", bsym, timeframe, year, month)
        csv_bytes = self._download_zip(url)
        if csv_bytes is None:
            return pd.DataFrame(columns=KLINE_COLUMNS)

        raw = pd.read_csv(
            io.BytesIO(csv_bytes),
            header=None,
            names=_BINANCE_KLINE_HEADER,
        )
        df = pd.DataFrame(
            {
                "timestamp": _normalize_epoch_ms(raw["openTime"]),
                "open": raw["open"].astype("float64"),
                "high": raw["high"].astype("float64"),
                "low": raw["low"].astype("float64"),
                "close": raw["close"].astype("float64"),
                "volume": raw["volume"].astype("float64"),
            }
        )
        df["symbol"] = symbol
        df["timeframe"] = timeframe
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = (
            df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        )
        logger.info(
            "Binance archive: %d bars %s %s %04d-%02d (%s)",
            len(df),
            symbol,
            timeframe,
            year,
            month,
            market,
        )
        return df

    def fetch_range(
        self,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
        *,
        market: str = "spot",
    ) -> pd.DataFrame:
        """Fetch all months in ``[start, end]`` (ISO ``YYYY-MM``) and concatenate.

        Returns an empty frame when every requested month is unavailable
        (e.g. a symbol listed after the requested window).
        """
        start_year, start_month = (int(x) for x in start.split("-")[:2])
        end_year, end_month = (int(x) for x in end.split("-")[:2])
        frames: list[pd.DataFrame] = []
        year, month = start_year, start_month
        while (year, month) <= (end_year, end_month):
            frame = self.fetch_monthly_klines(symbol, timeframe, year, month, market=market)
            if not frame.empty:
                frames.append(frame)
            month += 1
            if month > 12:
                month = 1
                year += 1
        if not frames:
            return pd.DataFrame(columns=[*KLINE_COLUMNS, "symbol", "timeframe", "datetime"])
        return pd.concat(frames, ignore_index=True)

    # ------------------------------------------------------------------
    # funding rates (futures only)
    # ------------------------------------------------------------------

    def fetch_monthly_funding(
        self, symbol: str, year: int, month: int, *, market: str = "futures"
    ) -> pd.DataFrame:
        """Fetch one month of funding rates (columns: timestamp, funding_rate).

        The archive fundingRate CSV has two columns: ``fundingTime`` (ms) and
        ``fundingRate`` (float, e.g. 0.0001 = 0.01%).
        """
        bsym = _to_binance_symbol(symbol)
        url = self._funding_url(market, bsym, year, month)
        csv_bytes = self._download_zip(url)
        if csv_bytes is None:
            return pd.DataFrame(columns=["timestamp", "funding_rate"])
        raw = pd.read_csv(io.BytesIO(csv_bytes))
        df = pd.DataFrame(
            {
                "timestamp": _normalize_epoch_ms(raw["fundingTime"]),
                "funding_rate": raw["fundingRate"].astype("float64"),
            }
        )
        df = (
            df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        )
        logger.info("Binance archive: %d funding rows %s %04d-%02d", len(df), symbol, year, month)
        return df

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _download_zip(self, url: str) -> bytes | None:
        """Download a monthly zip and return the first CSV member's bytes.

        Returns None when the archive has no such file (HTTP 404/403 — a
        symbol/timeframe/month combination that predates the listing).
        """
        logger.debug("Binance archive GET %s", url)
        try:
            with urllib.request.urlopen(url, timeout=self._timeout) as resp:
                payload = resp.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                # Genuine miss: symbol/timeframe/month predates the listing.
                logger.info("Binance archive miss: %s", url)
                return None
            raise DataError(f"Binance archive HTTP {e.code}: {url}") from e
        except Exception as e:
            # RV-007-005/H3: DNS/timeout/SSL/5xx are infrastructure failures,
            # not archive misses — swallowing them produced silent truncated
            # history that looked complete on disk.
            raise DataError(f"Binance archive download failed: {url}: {e}") from e
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                members = [n for n in zf.namelist() if n.endswith(".csv")]
                if not members:
                    logger.warning("Binance archive zip has no CSV member: %s", url)
                    return None
                return zf.read(members[0])
        except zipfile.BadZipFile:
            logger.warning("Binance archive returned a non-zip payload: %s", url)
            return None

    @staticmethod
    def _archive_url(
        market: str, kind: str, bsym: str, interval: str, year: int, month: int
    ) -> str:
        if market == "spot":
            path = f"spot/monthly/{kind}/{bsym}/{interval}/{bsym}-{interval}-{year:04d}-{month:02d}.zip"
        elif market == "futures":
            path = f"futures/um/monthly/{kind}/{bsym}/{interval}/{bsym}-{interval}-{year:04d}-{month:02d}.zip"
        else:
            raise DataError(f"Invalid market {market!r}. Valid: spot, futures")
        return f"{BINANCE_ARCHIVE_BASE}/{path}"

    @staticmethod
    def _funding_url(market: str, bsym: str, year: int, month: int) -> str:
        if market != "futures":
            raise DataError("Funding rates only exist on the futures market")
        return (
            f"{BINANCE_ARCHIVE_BASE}/futures/um/monthly/fundingRate/{bsym}/"
            f"{bsym}-fundingRate-{year:04d}-{month:02d}.zip"
        )


def download_binance_to_store(
    fetcher: BinanceArchiveFetcher,
    store: Any,
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    *,
    market: str = "spot",
    exchange_suffix: bool = True,
) -> pd.DataFrame:
    """Fetch a Binance range and persist it through the shared DataStore.

    Convenience used by the CLI; mirrors the OKX download flow
    (fetch → clean → store.save). When ``exchange_suffix`` is True the symbol
    is stored as ``<symbol>-BINANCE`` (e.g. ``BTC/USDT-BINANCE``) for exchange
    isolation — the symbol validator rejects ``.`` but allows ``-``.
    """
    from quantflow.data.cleaner import clean_ohlcv

    df = fetcher.fetch_range(symbol, timeframe, start, end, market=market)
    if df.empty:
        return df
    cleaned = clean_ohlcv(df)
    store_symbol = f"{symbol}-BINANCE" if exchange_suffix else symbol
    store.save(cleaned, store_symbol)
    return cleaned
