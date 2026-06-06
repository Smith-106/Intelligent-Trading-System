"""Parquet storage with DuckDB query layer."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

_SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9/_-]{1,20}$")
_COLUMN_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_symbol(symbol: str) -> str:
    """Validate symbol format to prevent SQL injection."""
    if not _SYMBOL_PATTERN.match(symbol):
        raise ValueError(
            f"Invalid symbol format: {symbol!r}. "
            "Only alphanumeric, /, _, - characters allowed (max 20 chars)."
        )
    return symbol.replace("/", "_")


def _validate_columns(columns: list[str] | tuple[str, ...] | None) -> list[str] | None:
    """Validate column names used in dynamically generated SQL."""
    if columns is None:
        return None
    if not columns:
        raise ValueError("columns must not be empty")
    invalid = [column for column in columns if not _COLUMN_PATTERN.match(column)]
    if invalid:
        raise ValueError(f"Invalid column name(s): {invalid!r}")
    return list(dict.fromkeys(columns))


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
                group_data = pd.concat(
                    [existing[DataStore.group_cols(existing)], group[data_cols]], ignore_index=True
                )
                group_data = group_data.drop_duplicates(subset=["timestamp"]).sort_values(
                    "timestamp"
                )
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
        columns: list[str] | tuple[str, ...] | None = None,
    ) -> pd.DataFrame:
        """Query stored data via DuckDB."""
        symbol_name = _validate_symbol(symbol)
        selected_columns = _validate_columns(columns)
        source = self._read_parquet_source(symbol_name, start, end)
        if source is None:
            return pd.DataFrame(columns=selected_columns or None)

        select_clause = "*" if selected_columns is None else ", ".join(selected_columns)
        conditions = []
        params: list[int | str] = []
        if start is not None:
            conditions.append("timestamp >= ?")
            params.append(int(start))
        if end is not None:
            conditions.append("timestamp <= ?")
            params.append(int(end))
        if timeframe is not None:
            conditions.append("timeframe = ?")
            params.append(timeframe)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""

        try:
            result = self._db.execute(
                f"""
                SELECT {select_clause} FROM read_parquet({source}){where}
                ORDER BY timestamp
                """,
                params,
            ).df()
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
        pattern = f"{self._parquet_dir.as_posix()}/{symbol_name}/*/*.parquet"
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

    def _read_parquet_source(
        self,
        symbol_name: str,
        start: int | None = None,
        end: int | None = None,
    ) -> str | None:
        symbol_dir = self._parquet_dir / symbol_name
        if not symbol_dir.exists():
            return None

        paths = self._candidate_paths(symbol_dir, start, end)
        if start is None and end is None:
            if not paths:
                pattern = f"{symbol_dir.as_posix()}/**/*.parquet"
                return f"'{pattern}'"
        if not paths:
            return None

        escaped = [f"'{path.as_posix().replace(chr(39), chr(39) + chr(39))}'" for path in paths]
        return f"[{', '.join(escaped)}]"

    @staticmethod
    def _candidate_paths(symbol_dir: Path, start: int | None, end: int | None) -> list[Path]:
        paths = sorted(symbol_dir.glob("*/*.parquet"))
        if start is None and end is None:
            return paths

        start_period = DataStore._timestamp_period(start, lower_bound=True)
        end_period = DataStore._timestamp_period(end, lower_bound=False)
        return [
            path for path in paths if start_period <= DataStore._path_period(path) <= end_period
        ]

    @staticmethod
    def _timestamp_period(timestamp: int | None, *, lower_bound: bool) -> tuple[int, int]:
        if timestamp is None:
            return (0, 1) if lower_bound else (9999, 12)
        dt = pd.to_datetime(timestamp, unit="ms", utc=True)
        return int(dt.year), int(dt.month)

    @staticmethod
    def _path_period(path: Path) -> tuple[int, int]:
        return int(path.parent.name), int(path.stem)

    @staticmethod
    def group_cols(df: pd.DataFrame) -> list[str]:
        return [c for c in df.columns if c not in {"year", "month"}]
