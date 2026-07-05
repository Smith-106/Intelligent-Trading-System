"""Feature Store — research and live trading share the same features."""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pandas as pd

from quantflow.common.validators import validate_symbol
from quantflow.data.store import DataStore

logger = logging.getLogger(__name__)


class FeatureStore:
    """Time-point-safe feature computation and storage."""

    def __init__(self, parquet_dir: str, duckdb_path: str = ":memory:") -> None:
        self._parquet_dir = Path(parquet_dir) / "features"
        self._parquet_dir.mkdir(parents=True, exist_ok=True)
        self._db = duckdb.connect(duckdb_path)

    def compute_features(
        self,
        symbol: str,
        timestamp: int,
        indicator_names: list[str],
        raw_store: DataStore | None = None,
    ) -> pd.DataFrame:
        """Compute features up to a given timestamp (no future data leak)."""
        if raw_store is None:
            raise ValueError("raw_store is required for feature computation")

        raw = raw_store.query(symbol, end=timestamp)
        if raw.empty:
            return pd.DataFrame()

        # Import and compute indicators
        from quantflow.indicators.engine import IndicatorEngine

        engine = IndicatorEngine()
        features = engine.compute_all(raw, indicator_names)

        features["symbol"] = symbol
        features["computed_at"] = timestamp
        return features

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
            combined = combined.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
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
                SELECT * FROM read_parquet({source}){where}
                ORDER BY timestamp
                """,
                params=params,
            ).df()
        except Exception as e:
            # Log rather than silently swallow (REV-010) — mirrors store.query().
            logger.warning("load_features failed for %s: %s", symbol, e)
            return pd.DataFrame()

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
