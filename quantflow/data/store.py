"""Parquet storage with DuckDB query layer."""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)


import re

_SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9/_-]{1,20}$")


def _validate_symbol(symbol: str) -> str:
    """Validate symbol format to prevent SQL injection."""
    if not _SYMBOL_PATTERN.match(symbol):
        raise ValueError(
            f"Invalid symbol format: {symbol!r}. "
            "Only alphanumeric, /, _, - characters allowed (max 20 chars)."
        )
    return symbol.replace("/", "_")


class DataStore:
    """Store OHLCV data as partitioned Parquet files and query via DuckDB."""

    def __init__(self, parquet_dir: str, duckdb_path: str = ":memory:") -> None:
        self._parquet_dir = Path(parquet_dir)
        self._parquet_dir.mkdir(parents=True, exist_ok=True)
        self._db = duckdb.connect(duckdb_path)
        self._duckdb_path = duckdb_path

    def save(self, df: pd.DataFrame, symbol: str) -> None:
        """Save DataFrame to Hive-partitioned Parquet (symbol/year/month)."""
        if df.empty:
            return

        store_df = df.copy()
        if "datetime" in store_df.columns:
            store_df["year"] = store_df["datetime"].dt.year
            store_df["month"] = store_df["datetime"].dt.month
        elif "timestamp" in store_df.columns:
            dt = pd.to_datetime(store_df["timestamp"], unit="ms", utc=True)
            store_df["year"] = dt.dt.year
            store_df["month"] = dt.dt.month
        else:
            raise ValueError("DataFrame must have 'datetime' or 'timestamp' column")

        symbol_dir = self._parquet_dir / symbol.replace("/", "_")
        symbol_dir.mkdir(parents=True, exist_ok=True)

        # Write partitioned parquet
        partition_cols = ["year", "month"]
        data_cols = [c for c in store_df.columns if c not in partition_cols]

        for (year, month), group in store_df.groupby(partition_cols):
            year_dir = symbol_dir / str(int(year))
            month_path = year_dir / f"{int(month):02d}.parquet"

            existing = self._load_existing(month_path)
            if existing is not None:
                group_data = pd.concat([existing[DataStore.group_cols(existing)], group[data_cols]], ignore_index=True)
                group_data = group_data.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
            else:
                year_dir.mkdir(parents=True, exist_ok=True)
                group_data = group[data_cols]

            group_data.to_parquet(month_path, index=False, compression="zstd")

        logger.info("Saved %d bars for %s to %s", len(df), symbol, symbol_dir)

    def query(
        self,
        symbol: str,
        start: int | None = None,
        end: int | None = None,
        timeframe: str | None = None,
    ) -> pd.DataFrame:
        """Query stored data via DuckDB."""
        symbol_name = symbol.replace("/", "_")
        # Use forward slashes for DuckDB glob pattern (cross-platform)
        pattern = f"{self._parquet_dir.as_posix()}/{symbol_name}/**/*.parquet"

        conditions = []
        if start is not None:
            conditions.append(f"timestamp >= {start}")
        if end is not None:
            conditions.append(f"timestamp <= {end}")
        if timeframe is not None:
            conditions.append(f"timeframe = '{timeframe}'")

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""

        try:
            result = self._db.query(f"""
                SELECT * FROM read_parquet('{pattern}'){where}
                ORDER BY timestamp
            """).df()
            return result
        except Exception as e:
            logger.warning("Query failed for %s: %s", symbol, e)
            return pd.DataFrame()

    def list_symbols(self) -> list[str]:
        """List all stored symbols."""
        symbols = []
        for d in self._parquet_dir.iterdir():
            if d.is_dir():
                symbols.append(d.name)
        return sorted(symbols)

    def get_date_range(self, symbol: str) -> tuple[int, int] | None:
        """Get the date range of stored data for a symbol."""
        symbol_name = symbol.replace("/", "_")
        pattern = f"{self._parquet_dir.as_posix()}/{symbol_name}/*/*/*.parquet"
        try:
            result = self._db.query(f"""
                SELECT MIN(timestamp) as min_ts, MAX(timestamp) as max_ts
                FROM read_parquet('{pattern}')
            """).fetchone()
            if result and result[0] is not None:
                return (result[0], result[1])
        except Exception:
            pass
        return None

    def close(self) -> None:
        self._db.close()

    def _load_existing(self, path: Path) -> pd.DataFrame | None:
        if path.exists():
            return pd.read_parquet(path)
        return None

    @staticmethod
    def group_cols(df: pd.DataFrame) -> list[str]:
        return [c for c in df.columns if c not in {"year", "month"}]
