"""Feature Store — research and live trading share the same features."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from quantflow.common.exceptions import DataError
from quantflow.common.indicator_protocol import IndicatorComputer, NullIndicatorComputer
from quantflow.common.validators import validate_symbol
from quantflow.data.store import DataStore

logger = logging.getLogger(__name__)


class FeatureStore:
    """Time-point-safe feature computation and storage."""

    def __init__(
        self,
        parquet_dir: str,
        duckdb_path: str = ":memory:",
        indicator_computer: IndicatorComputer | None = None,
        meta_computer: Any | None = None,
    ) -> None:
        """Initialize FeatureStore.

        Args:
            parquet_dir: Root directory for Parquet feature storage.
            duckdb_path: Path to DuckDB file (default: in-memory).
            indicator_computer: Optional IndicatorComputer for compute_features().
                Defaults to NullIndicatorComputer (raises ValueError if used).
            meta_computer: Optional L2 meta-feature computer (s3 T-s3-02,
                ``MetaFeatureComputer`` protocol: compute_meta_features(features,
                funding, open_interest) -> features+meta columns). Injected to
                keep L1→L2 one-way dependency. Defaults to None = no meta
                features (zero behavior change).
        """
        self._parquet_dir = Path(parquet_dir) / "features"
        self._parquet_dir.mkdir(parents=True, exist_ok=True)
        self._db = duckdb.connect(duckdb_path)
        self._indicator_computer = indicator_computer or NullIndicatorComputer()
        self._meta_computer = meta_computer

    def compute_features(
        self,
        symbol: str,
        timestamp: int,
        indicator_names: list[str],
        raw_store: DataStore | None = None,
        meta_store: DataStore | None = None,
    ) -> pd.DataFrame:
        """Compute features up to a given timestamp (no future data leak).

        Args:
            symbol: Trading symbol.
            timestamp: Point-in-time cutoff (ms).
            indicator_names: Indicators to compute.
            raw_store: OHLCV DataStore (required).
            meta_store: Optional DataStore for funding-rate / open-interest
                meta features (s3 T-s3-02). When provided AND a
                ``meta_computer`` was injected at construction, funding/OI
                features are appended via as-of join at ``timestamp``.
        """
        if raw_store is None:
            raise ValueError("raw_store is required for feature computation")

        raw = raw_store.query(symbol, end=timestamp)
        if raw.empty:
            return pd.DataFrame()

        # ISS-002: use injected IndicatorComputer Protocol instead of direct
        # L1→L2 import. NullIndicatorComputer raises a descriptive error if
        # no implementation was provided.
        features = self._indicator_computer.compute_all(raw, indicator_names)

        # s3 T-s3-02: meta-market features (funding_rate / open interest),
        # point-in-time via meta_store.query_*_rates(end=timestamp).
        if self._meta_computer is not None and meta_store is not None:
            features = self._append_meta_features(features, symbol, timestamp, meta_store)

        features["symbol"] = symbol
        features["computed_at"] = timestamp
        return features

    def _append_meta_features(
        self,
        features: pd.DataFrame,
        symbol: str,
        timestamp: int,
        meta_store: DataStore,
    ) -> pd.DataFrame:
        """Append funding/OI features with as-of join at ``timestamp``."""
        funding = meta_store.query_funding_rates(symbol, end=timestamp)
        oi = meta_store.query_open_interest(symbol, end=timestamp)
        computer = self._meta_computer
        if computer is None:
            return features
        out = computer.compute_meta_features(features, funding, oi)
        if "timestamp" not in out.columns and "timestamp" in features.columns:
            out["timestamp"] = features["timestamp"]
        return out

    def save_features(self, symbol: str, features: pd.DataFrame) -> None:
        """Persist computed features to Parquet."""
        if features.empty:
            return

        # SECURITY: validate symbol on the write path (REV-008) — mirrors the
        # read-side check in load_features so a user-supplied symbol cannot
        # traverse the parquet dir.
        symbol_dir = self._parquet_dir / validate_symbol(symbol)
        symbol_dir.mkdir(parents=True, exist_ok=True)

        store_df = features.copy()
        if "datetime" in store_df.columns:
            if "timestamp" not in store_df.columns:
                dt = pd.to_datetime(store_df["datetime"], utc=True)
                store_df["timestamp"] = dt.map(lambda value: int(value.timestamp() * 1000))
            store_df["year"] = store_df["datetime"].dt.year
            store_df["month"] = store_df["datetime"].dt.month
        elif "timestamp" in store_df.columns:
            dt = pd.to_datetime(store_df["timestamp"], unit="ms", utc=True)
            store_df["year"] = dt.dt.year
            store_df["month"] = dt.dt.month
        else:
            raise ValueError("Features must have 'datetime' or 'timestamp' column")

        for (year, month), group in store_df.groupby(["year", "month"]):
            year_dir = symbol_dir / str(int(year))
            year_dir.mkdir(parents=True, exist_ok=True)
            month_path = year_dir / f"{int(month):02d}.parquet"

            existing = pd.read_parquet(month_path) if month_path.exists() else pd.DataFrame()
            combined = pd.concat([existing, group], ignore_index=True)
            # W19a: explicit keep="first" — existing / earlier rows win. Prevents a
            # later backfill from silently overwriting a PIT feature row at the
            # same timestamp (anti-lookahead write path). Conflicts are logged.
            before = len(combined)
            combined = combined.drop_duplicates(subset=["timestamp"], keep="first").sort_values(
                "timestamp"
            )
            dropped = before - len(combined)
            if dropped > 0:
                logger.warning(
                    "FeatureStore.save_features: dropped %d duplicate timestamp row(s) "
                    "for %s (keep=first / existing wins)",
                    dropped,
                    symbol,
                )
            combined.to_parquet(month_path, index=False, compression="zstd")

        logger.info("Saved %d feature rows for %s", len(features), symbol)

    def load_features(
        self,
        symbol: str,
        start: int | None = None,
        end: int | None = None,
    ) -> pd.DataFrame:
        """Load historical features for backtesting."""
        # SECURITY: validate symbol (prevents path traversal in _read_feature_source
        # and SQL injection via the read_parquet source) and parameterize start/end
        # rather than f-string interpolating them into the WHERE clause.
        symbol_name = validate_symbol(symbol)
        source = self._read_feature_source(symbol_name, start, end)
        if source is None:
            return pd.DataFrame()

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
            return self._db.query(
                f"""
                SELECT * FROM read_parquet({source}, union_by_name=true){where}
                ORDER BY timestamp
                """,
                params=params,
            ).df()
        except Exception as e:
            # ISS-20260723-014 (GP1 fail-silent): storage error → raise, not
            # return empty DF. "No data" (source None) returns empty DF at
            # line 100 above — distinct from this failure path. Mirrors store.query().
            logger.warning("load_features failed for %s: %s", symbol, e)
            raise DataError(f"load_features failed for {symbol!r}: {e}") from e

    def close(self) -> None:
        self._db.close()

    def _read_feature_source(
        self,
        symbol_name: str,
        start: int | None = None,
        end: int | None = None,
    ) -> str | None:
        symbol_dir = self._parquet_dir / symbol_name
        legacy_path = symbol_dir / "features.parquet"
        if legacy_path.exists():
            return f"'{legacy_path.as_posix()}'"
        if not symbol_dir.exists():
            return None

        # No filter → hand DuckDB a glob literal directly instead of
        # materializing the path list and string-building a SQL array (REV-014).
        # Probe once so an empty dir returns None (clean "no data") rather than
        # a glob matching zero files, which DuckDB errors on.
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

        start_period = FeatureStore._timestamp_period(start, lower_bound=True)
        end_period = FeatureStore._timestamp_period(end, lower_bound=False)
        return [
            path for path in paths if start_period <= FeatureStore._path_period(path) <= end_period
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
