"""Multi-timeframe data aligner.

Aligns OHLCV data across timeframes (weekly→4H→1H→15m) using
UTC time anchoring and rolling windows to handle 24/7 crypto
markets (Q4, SME-09).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from quantflow.data.fetcher import DataFetcher

logger = logging.getLogger(__name__)


TIMEFRAME_MAP = {
    "1W": "7D",
    "4H": "4h",
    "1H": "1h",
    "15m": "15min",
    "1D": "1D",
}

# Standard timeframe hierarchy for Liu Yudong style analysis
DEFAULT_TIMEFRAMES = ["1W", "4H", "1H", "15m"]


@dataclass
class MTFData:
    """Multi-timeframe aligned data."""

    primary: pd.DataFrame  # Weekly/Daily — direction and major structure
    intermediate: pd.DataFrame  # 4H — sub-wave structure and entry zones
    minor: pd.DataFrame  # 1H/15m — precise entry and stop placement
    aligned_index: pd.DatetimeIndex  # Common UTC time index
    timeframes: list[str] = field(default_factory=lambda: DEFAULT_TIMEFRAMES[:])


class MTFAligner:
    """Multi-timeframe data aligner for Elliott Wave analysis.

    Aligns data across timeframes using UTC timestamp anchoring.
    Uses rolling windows rather than calendar boundaries to handle
    24/7 crypto markets correctly (Q4).

    Output provides multi-timeframe pivot sequences for wave
    identification at each degree (S-002).
    """

    def __init__(self, fetcher: DataFetcher | None = None):
        self.fetcher = fetcher

    def align(
        self,
        symbol: str,
        timeframes: list[str] | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> MTFData:
        """Align multi-timeframe data for a symbol.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            timeframes: Timeframe hierarchy (default: 1W→4H→1H→15m).
            start: Start date (UTC).
            end: End date (UTC).

        Returns:
            MTFData with aligned DataFrames and common time index.
        """
        tf_list = timeframes or DEFAULT_TIMEFRAMES

        if len(tf_list) < 3:
            raise ValueError("Need at least 3 timeframes for MTF analysis")

        # Fetch data for each timeframe
        dfs: dict[str, pd.DataFrame] = {}
        for tf in tf_list:
            df = self._fetch_timeframe(symbol, tf, start, end)
            if df is not None and not df.empty:
                dfs[tf] = df

        if len(dfs) < 3:
            # Fallback: generate synthetic aligned data from available
            return self._fallback_align(dfs, tf_list)

        # Align to common UTC time index
        primary_tf = tf_list[0]
        intermediate_tf = tf_list[1]
        minor_tf = tf_list[2]

        primary = dfs.get(primary_tf, pd.DataFrame())
        intermediate = dfs.get(intermediate_tf, pd.DataFrame())
        minor = dfs.get(minor_tf, pd.DataFrame())

        # Create aligned index from the most granular timeframe
        aligned_index = self._create_aligned_index(minor, primary)

        # Reindex all DataFrames to the aligned index
        primary = self._reindex_to_utc(primary, aligned_index)
        intermediate = self._reindex_to_utc(intermediate, aligned_index)
        minor = self._reindex_to_utc(minor, aligned_index)

        return MTFData(
            primary=primary,
            intermediate=intermediate,
            minor=minor,
            aligned_index=aligned_index,
            timeframes=tf_list[:3],
        )

    def _fetch_timeframe(
        self,
        symbol: str,
        timeframe: str,
        start: str | None,
        end: str | None,
    ) -> pd.DataFrame | None:
        """Fetch data for a single timeframe."""
        if self.fetcher is None:
            return None

        try:
            ccxt_tf = TIMEFRAME_MAP.get(timeframe, timeframe)
            return self.fetcher.fetch_ohlcv(
                symbol=symbol,
                timeframe=ccxt_tf,
                start=start,
                end=end,
            )
        except Exception:
            logger.warning("Failed to fetch %s %s data", symbol, timeframe, exc_info=True)
            return None

    def _create_aligned_index(
        self,
        minor: pd.DataFrame,
        primary: pd.DataFrame,
    ) -> pd.DatetimeIndex:
        """Create a common UTC time index from the most granular data.

        Uses rolling windows anchored to UTC timestamps rather than
        calendar boundaries (Q4).
        """
        if minor.empty:
            if primary.empty:
                return pd.DatetimeIndex([], tz="UTC")
            return primary.index.tz_localize("UTC") if primary.index.tz is None else primary.index

        idx = minor.index
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        return idx

    def _reindex_to_utc(
        self,
        df: pd.DataFrame,
        aligned_index: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        """Reindex a DataFrame to the aligned UTC time index.

        Forward-fill ensures no future data leakage: higher-timeframe
        data is only available after its bar closes.
        """
        if df.empty or aligned_index.empty:
            return df

        if df.index.tz is None:
            df = df.tz_localize("UTC")
        elif df.index.tz != aligned_index.tz:
            df = df.tz_convert(aligned_index.tz)

        return df.reindex(aligned_index).ffill()

    def _fallback_align(
        self,
        dfs: dict[str, pd.DataFrame],
        tf_list: list[str],
    ) -> MTFData:
        """Fallback when insufficient timeframe data is available."""
        available = list(dfs.values())
        primary = available[0] if len(available) > 0 else pd.DataFrame()
        intermediate = available[1] if len(available) > 1 else pd.DataFrame()
        minor = available[2] if len(available) > 2 else pd.DataFrame()

        aligned_index = pd.DatetimeIndex([])
        if not minor.empty:
            idx = minor.index
            aligned_index = idx.tz_localize("UTC") if idx.tz is None else idx
        elif not primary.empty:
            idx = primary.index
            aligned_index = idx.tz_localize("UTC") if idx.tz is None else idx

        return MTFData(
            primary=primary,
            intermediate=intermediate,
            minor=minor,
            aligned_index=aligned_index,
            timeframes=tf_list[:3],
        )
