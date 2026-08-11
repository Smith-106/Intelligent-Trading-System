"""QuantFlow data layer: fetching, cleaning, storage, and feature engineering."""

from typing import Any

from quantflow.data.cleaner import clean_ohlcv, validate_no_future_leak
from quantflow.data.feature_store import FeatureStore
from quantflow.data.fetcher import DataFetcher
from quantflow.data.pit_audit import PITAuditError, run_pit_audit_suite
from quantflow.data.store import DataStore

__all__ = [
    "DataFetcher",
    "DataStore",
    "FeatureStore",
    "PITAuditError",
    "RedisCache",
    "clean_ohlcv",
    "run_pit_audit_suite",
    "validate_no_future_leak",
]


def __getattr__(name: str) -> Any:
    """Load optional cache integrations only when explicitly requested."""
    if name == "RedisCache":
        from quantflow.data.redis_cache import RedisCache

        return RedisCache
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
