"""Feature Store — research and live trading share the same features."""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pandas as pd

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

        symbol_dir = self._parquet_dir / symbol.replace("/", "_")
        symbol_dir.mkdir(parents=True, exist_ok=True)

        if "datetime" in features.columns:
            features["year"] = features["datetime"].dt.year
            features["month"] = features["datetime"].dt.month
        elif "timestamp" in features.columns:
            dt = pd.to_datetime(features["timestamp"], unit="ms", utc=True)
            features["year"] = dt.dt.year
            features["month"] = dt.dt.month

        path = symbol_dir / "features.parquet"
        existing = pd.read_parquet(path) if path.exists() else pd.DataFrame()
        combined = pd.concat([existing, features], ignore_index=True)
        combined = combined.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
        combined.to_parquet(path, index=False, compression="zstd")

        logger.info("Saved %d feature rows for %s", len(features), symbol)

    def load_features(
        self,
        symbol: str,
        start: int | None = None,
        end: int | None = None,
    ) -> pd.DataFrame:
        """Load historical features for backtesting."""
        symbol_name = symbol.replace("/", "_")
        path = self._parquet_dir / symbol_name / "features.parquet"
        if not path.exists():
            return pd.DataFrame()

        conditions = []
        if start is not None:
            conditions.append(f"timestamp >= {start}")
        if end is not None:
            conditions.append(f"timestamp <= {end}")
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""

        try:
            return self._db.query(f"""
                SELECT * FROM read_parquet('{path}'){where}
                ORDER BY timestamp
            """).df()
        except Exception:
            return pd.DataFrame()

    def close(self) -> None:
        self._db.close()
