"""Parquet storage with DuckDB query layer."""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pandas as pd

from quantflow.common.exceptions import DataError
from quantflow.common.validators import (
    COLUMN_PATTERN,
    SYMBOL_PATTERN,
)
from quantflow.common.validators import (
    validate_columns as _validate_columns_impl,
)
from quantflow.common.validators import (
    validate_symbol as _validate_symbol_impl,
)

logger = logging.getLogger(__name__)

# Public patterns re-exported for back-compat / introspection.
_SYMBOL_PATTERN = SYMBOL_PATTERN
_COLUMN_PATTERN = COLUMN_PATTERN

# T-s2-02: meta data types live in dedicated top-level directories so they
# can never pollute OHLCV symbol dirs (get_date_range / timeframe queries).
META_DATA_TYPES: dict[str, str] = {
    "funding_rate": "meta_funding_rate",
    "open_interest": "meta_open_interest",
}
#: Required columns per meta type (timestamp ms int; T-s2-01 column contract).
META_REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "funding_rate": ("timestamp", "funding_rate", "realized_rate", "funding_time"),
    "open_interest": (
        "timestamp",
        "open_interest",
        "open_interest_ccy",
        "open_interest_usd",
    ),
}


def _validate_symbol(symbol: str) -> str:
    """Back-compat alias for :func:`quantflow.common.validators.validate_symbol`."""
    return _validate_symbol_impl(symbol)


def _validate_columns(columns: list[str] | tuple[str, ...] | None) -> list[str] | None:
    """Back-compat alias for :func:`quantflow.common.validators.validate_columns`."""
    return _validate_columns_impl(columns)


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

        # SECURITY: validate symbol on the write path too (REV-008) — the read
        # path (query/get_date_range) validates, but save() previously did a
        # bare symbol.replace('/', '_'), leaving a path-traversal surface for
        # a future caller passing user input. Mirrors the read-side choke point.
        symbol_name = _validate_symbol(symbol)
        self._save_partitioned(df, symbol_name, self._parquet_dir)
        logger.info("Saved %d bars for %s", len(df), symbol)

    def _save_partitioned(self, df: pd.DataFrame, symbol_name: str, base_dir: Path) -> None:
        """Shared Hive-partition writer (OHLCV save + meta saves, T-s2-02).

        Layout: <base_dir>/<symbol>/YYYY/MM.parquet with append-only fast
        path + keep='last' merge on overlap (ISS-034 semantics preserved).
        """
        store_df = df.copy()
        # Timestamp column contract: int64 epoch-milliseconds in ALL partitions
        # (matching the historical 1d files). clean_ohlcv converts to datetime;
        # normalize back to ms int so a mixed month never holds BIGINT next to
        # TIMESTAMP (DuckDB multi-partition reads then fail to cast).
        if "timestamp" in store_df.columns and pd.api.types.is_datetime64_any_dtype(
            store_df["timestamp"]
        ):
            store_df["timestamp"] = (
                store_df["timestamp"].values.astype("datetime64[ms]").astype("int64")
            )
        if "datetime" in store_df.columns:
            store_df["year"] = store_df["datetime"].dt.year
            store_df["month"] = store_df["datetime"].dt.month
        elif "timestamp" in store_df.columns:
            dt = pd.to_datetime(store_df["timestamp"], unit="ms", utc=True)
            store_df["year"] = dt.dt.year
            store_df["month"] = dt.dt.month
        else:
            raise ValueError("DataFrame must have 'datetime' or 'timestamp' column")

        symbol_dir = base_dir / symbol_name
        symbol_dir.mkdir(parents=True, exist_ok=True)

        # Write partitioned parquet
        partition_cols = ["year", "month"]
        data_cols = [c for c in store_df.columns if c not in partition_cols]

        for (year, month), group in store_df.groupby(partition_cols):
            year_dir = symbol_dir / str(int(year))
            month_path = year_dir / f"{int(month):02d}.parquet"

            existing = self._load_existing(month_path)
            if existing is not None:
                existing_group = existing[DataStore.group_cols(existing)]
                new_group = group[data_cols]
                # ISS-034: append-only fast path. The common live/incremental
                # case appends bars whose timestamps are all newer than the
                # stored max — no overlap, both sides already timestamp-sorted,
                # so concat is already sorted and dedup is a no-op. Skip the
                # O(n) drop_duplicates + sort_values + reset_index on the full
                # month (the prior code rewrote + resorted the entire partition
                # for every save, even a 1-bar append to a 720-row month).
                # Fall back to the full merge only when timestamps overlap (a
                # backfill/replay re-saving existing bars), where keep="last"
                # (newer wins) must actually run.
                existing_max = existing_group["timestamp"].max()
                new_min = new_group["timestamp"].min()
                if new_min > existing_max:
                    group_data = pd.concat(
                        [existing_group, new_group],
                        ignore_index=True,
                        sort=False,
                    )
                else:
                    group_data = pd.concat(
                        [existing_group, new_group],
                        ignore_index=True,
                        sort=False,
                    )
                    group_data = (
                        group_data.drop_duplicates(subset=["timestamp"], keep="last")
                        .sort_values("timestamp")
                        .reset_index(drop=True)
                    )
            else:
                year_dir.mkdir(parents=True, exist_ok=True)
                group_data = group[data_cols]

            group_data.to_parquet(month_path, index=False, compression="zstd")

    # ------------------------------------------------------------------
    # T-s2-02: market meta data (funding rate / open interest)
    # ------------------------------------------------------------------

    def save_funding_rates(self, df: pd.DataFrame, symbol: str) -> None:
        """Persist funding-rate history under meta_funding_rate/<symbol>/.

        Column contract: [timestamp, funding_rate, realized_rate,
        funding_time, next_funding_rate?] with timestamp as ms int.
        Symbol is validated on the write path (REV-008). Re-save of the same
        timestamp is keep='last' deduped (incremental replay safe).
        """
        self._save_meta(df, symbol, "funding_rate")

    def save_open_interest(self, df: pd.DataFrame, symbol: str) -> None:
        """Persist open-interest history under meta_open_interest/<symbol>/.

        Column contract: [timestamp, open_interest, open_interest_ccy,
        open_interest_usd] with timestamp as ms int.
        """
        self._save_meta(df, symbol, "open_interest")

    def _save_meta(self, df: pd.DataFrame, symbol: str, data_type: str) -> None:
        if data_type not in META_DATA_TYPES:
            raise ValueError(
                f"Invalid meta data_type: {data_type!r}. Allowed: {sorted(META_DATA_TYPES)}"
            )
        if df.empty:
            return
        required = META_REQUIRED_COLUMNS[data_type]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise DataError(f"{data_type} frame missing required columns: {missing}")
        symbol_name = _validate_symbol(symbol)  # REV-008 write-path validation
        base_dir = self._parquet_dir / META_DATA_TYPES[data_type]
        self._save_partitioned(df, symbol_name, base_dir)
        logger.info("Saved %d %s rows for %s", len(df), data_type, symbol)

    def query_funding_rates(
        self,
        symbol: str,
        start: int | None = None,
        end: int | None = None,
    ) -> pd.DataFrame:
        """Query funding-rate history via DuckDB (point-in-time via ``end``)."""
        return self._query_meta("funding_rate", symbol, start, end)

    def query_open_interest(
        self,
        symbol: str,
        start: int | None = None,
        end: int | None = None,
    ) -> pd.DataFrame:
        """Query open-interest history via DuckDB (point-in-time via ``end``)."""
        return self._query_meta("open_interest", symbol, start, end)

    def _query_meta(
        self,
        data_type: str,
        symbol: str,
        start: int | None,
        end: int | None,
    ) -> pd.DataFrame:
        if data_type not in META_DATA_TYPES:
            raise ValueError(
                f"Invalid meta data_type: {data_type!r}. Allowed: {sorted(META_DATA_TYPES)}"
            )
        symbol_name = _validate_symbol(symbol)  # SQL-glob injection guard
        meta_dir = self._parquet_dir / META_DATA_TYPES[data_type] / symbol_name
        if not meta_dir.exists() or not any(meta_dir.glob("*/*.parquet")):
            return pd.DataFrame(columns=list(META_REQUIRED_COLUMNS[data_type]))
        # Escape single quotes so a parquet_dir containing a quote cannot
        # break the glob literal (mirrors _read_parquet_source / get_date_range).
        pattern = f"{meta_dir.as_posix()}/**/*.parquet".replace(chr(39), chr(39) * 2)
        conditions: list[str] = []
        params: list[int] = []
        if start is not None:
            conditions.append("timestamp >= ?")
            params.append(int(start))
        if end is not None:
            conditions.append("timestamp <= ?")
            params.append(int(end))
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        try:
            return self._db.execute(
                f"""
                SELECT * FROM read_parquet('{pattern}', union_by_name=true){where}
                ORDER BY timestamp
                """,
                params,
            ).df()
        except Exception as e:
            # Fail-silent distinction (ISS-20260723-013 pattern): storage
            # error raises DataError; "no data" returned an empty frame above.
            logger.warning("Meta query failed for %s %s: %s", data_type, symbol, e)
            raise DataError(f"Meta query failed for {data_type!r} {symbol!r}: {e}") from e

    def get_last_meta_timestamp(self, symbol: str, data_type: str) -> int | None:
        """Last stored timestamp for a meta data type.

        ``data_type`` is allowlisted (mirrors get_last_timestamp's injection
        guard). Returns None when no data exists yet (dir probe); raises
        DataError on storage failure (ISS-20260723-016 fail-silent pattern).
        """
        if data_type not in META_DATA_TYPES:
            raise ValueError(
                f"Invalid meta data_type: {data_type!r}. Allowed: {sorted(META_DATA_TYPES)}"
            )
        symbol_name = _validate_symbol(symbol)
        meta_dir = self._parquet_dir / META_DATA_TYPES[data_type] / symbol_name
        if not meta_dir.exists():
            return None
        pattern = f"{meta_dir.as_posix()}/**/*.parquet".replace(chr(39), chr(39) * 2)
        try:
            result = self._db.query(
                f"""
                SELECT MAX(timestamp) as max_ts
                FROM read_parquet('{pattern}', union_by_name=true)
                """
            ).fetchone()
            if result and result[0] is not None:
                return int(result[0])
        except Exception as e:
            logger.warning(
                "get_last_meta_timestamp failed for %s %s: %s", data_type, symbol, e
            )
            raise DataError(
                f"get_last_meta_timestamp failed for {data_type!r} {symbol!r}: {e}"
            ) from e
        return None

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
                SELECT {select_clause} FROM read_parquet({source}, union_by_name=true){where}
                ORDER BY timestamp
                """,
                params,
            ).df()
            return result
        except Exception as e:
            # ISS-20260723-013 (GP1 fail-silent): a DuckDB execution failure is
            # a storage error, not "no data" — raise so callers can distinguish
            # (the "no data" path returns an empty DF at line 133-134 above,
            # indistinguishable before this fix). Logged before raise so the
            # server log retains the raw error for diagnostics.
            logger.warning("Query failed for %s: %s", symbol, e)
            raise DataError(f"Query failed for {symbol!r}: {e}") from e

    def list_symbols(self) -> list[str]:
        """List all stored OHLCV symbols (meta_* data dirs excluded, T-s2-02)."""
        symbols = []
        for d in self._parquet_dir.iterdir():
            if d.is_dir() and d.name not in META_DATA_TYPES.values():
                symbols.append(d.name)
        return sorted(symbols)

    def get_date_range(self, symbol: str) -> tuple[int, int] | None:
        """Get the date range of stored data for a symbol."""
        # SECURITY: validate symbol before interpolating into the DuckDB
        # read_parquet glob string. Without this, a crafted symbol containing
        # a single quote could break out of the glob literal and inject
        # arbitrary SQL (e.g. read_csv_auto('/etc/passwd')). Mirrors query().
        symbol_name = _validate_symbol(symbol)
        # ISS-20260723-014 (GP1 fail-silent): probe the symbol dir before the
        # glob query so "no data for this symbol" returns None cleanly —
        # distinct from a DuckDB execution failure (raised below). Without this
        # an unknown symbol hits DuckDB's "No files found" IO Error, which the
        # except block would now raise as DataError, breaking callers that
        # legitimately treat None as "no history yet" (e.g. incremental download).
        symbol_dir = self._parquet_dir / symbol_name
        if not symbol_dir.exists():
            return None
        # Escape single quotes so a parquet_dir containing a quote cannot break
        # the glob literal (mirrors _read_parquet_source's chr(39) escaping).
        pattern = f"{self._parquet_dir.as_posix()}/{symbol_name}/*/*.parquet".replace("'", "''")
        try:
            result = self._db.query(f"""
                SELECT MIN(timestamp) as min_ts, MAX(timestamp) as max_ts
                FROM read_parquet('{pattern}', union_by_name=true)
            """).fetchone()
            if result and result[0] is not None:
                return (result[0], result[1])
        except Exception as e:
            # ISS-20260723-014 (GP1 fail-silent): storage error → raise, not
            # return None. "No data" (dir missing above, or result empty) returns
            # None at the fallthrough below — distinct from this failure path.
            logger.warning("get_date_range failed for %s: %s", symbol, e)
            raise DataError(f"get_date_range failed for {symbol!r}: {e}") from e
        return None

    def get_last_timestamp(self, symbol: str, timeframe: str) -> int | None:
        """Get the last stored timestamp for a symbol+timeframe.

        ISS-027: the layer-correct owner of parquet reads. Previously
        ``DataFetcher.get_last_timestamp`` hand-rolled an equivalent DuckDB
        ``read_parquet`` glob query against this store's on-disk layout,
        duplicating the glob construction + symbol validation (drift risk:
        the two globs used different depth — ``/*/*/*.parquet`` vs
        ``/*/*.parquet`` — and could silently diverge). The fetcher now
        delegates here so the read path has one owner.

        ``timeframe`` is parameterized (not interpolated) so a crafted value
        cannot inject SQL; it is also allowlisted via TIMEFRAMES so a typo
        cannot silently return None (mimicking "no data").
        """
        from quantflow.data.fetcher import TIMEFRAMES

        symbol_name = _validate_symbol(symbol)
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"Invalid timeframe: {timeframe!r}. Allowed: {TIMEFRAMES}")
        # ISS-20260723-016 (GP1 fail-silent): probe the symbol dir before the
        # glob query so "no data for this symbol" returns None cleanly —
        # distinct from a DuckDB execution failure (raised below). Mirrors
        # get_date_range + _read_parquet_source.
        symbol_dir = self._parquet_dir / symbol_name
        if not symbol_dir.exists():
            return None
        pattern = f"{self._parquet_dir.as_posix()}/{symbol_name}/*/*.parquet".replace("'", "''")
        try:
            result = self._db.query(
                f"""
                SELECT MAX(timestamp) as max_ts
                FROM read_parquet('{pattern}', union_by_name=true)
                WHERE timeframe = ?
                """,
                params=[timeframe],
            ).fetchone()
            if result and result[0] is not None:
                return int(result[0])
        except Exception as e:
            # ISS-20260723-016 (GP1 fail-silent): storage error → raise, not
            # return None. "No data" (result empty) falls through to return None
            # below — distinct from this failure path. Lets the fetcher caller
            # distinguish "no history yet" (None) from "query broke" (raise).
            logger.warning("get_last_timestamp failed for %s %s: %s", symbol, timeframe, e)
            raise DataError(f"get_last_timestamp failed for {symbol!r} {timeframe!r}: {e}") from e
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

        # When no start/end filter is applied, hand DuckDB a glob literal
        # directly instead of materializing the path list and string-building
        # a SQL array — a single glob lets DuckDB push the scan into the
        # reader, avoiding an O(N) Python loop + a larger query string as the
        # partition count grows (REV-014). We still probe the directory once
        # so an empty symbol dir returns None (clean "no data") rather than a
        # glob matching zero files, which DuckDB errors on.
        if start is None and end is None:
            if not any(symbol_dir.glob("*/*.parquet")):
                return None
            pattern = f"{symbol_dir.as_posix()}/**/*.parquet"
            return f"'{pattern}'"

        paths = self._candidate_paths(symbol_dir, start, end)
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
