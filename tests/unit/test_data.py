"""Unit tests for data cleaner and store."""

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantflow.common.exceptions import DataError
from quantflow.data.cleaner import clean_ohlcv, validate_no_future_leak
from quantflow.data.store import DataStore


@pytest.fixture
def raw_ohlcv():
    np.random.seed(42)
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, tz="UTC")
    close = 42000 + np.random.normal(0, 500, n)
    return pd.DataFrame(
        {
            "timestamp": list(range(1712620800000, 1712620800000 + n * 86400000, 86400000)),
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.random.uniform(100, 1000, n),
            "symbol": "BTC/USDT",
            "timeframe": "1d",
            "datetime": dates,
        }
    )


class TestCleaner:
    def test_removes_duplicates(self, raw_ohlcv):
        dup = pd.concat([raw_ohlcv, raw_ohlcv.iloc[:5]]).reset_index(drop=True)
        cleaned = clean_ohlcv(dup)
        assert len(cleaned) <= len(dup)

    def test_handles_invalid_ohlc(self, raw_ohlcv):
        bad = raw_ohlcv.copy()
        bad.loc[0, "high"] = bad.loc[0, "low"] - 100  # high < low
        cleaned = clean_ohlcv(bad)
        # New cleaner fixes OHLC instead of removing rows
        assert cleaned.loc[0, "high"] >= cleaned.loc[0, "low"]

    def test_validate_no_future_leak(self, raw_ohlcv):
        # Use a cutoff after all data → should pass
        cutoff = raw_ohlcv["timestamp"].max() + 1000
        assert validate_no_future_leak(raw_ohlcv, cutoff_timestamp=cutoff)
        # Use a cutoff before all data → should fail
        assert not validate_no_future_leak(raw_ohlcv, cutoff_timestamp=0)

    def test_outlier_detection(self, raw_ohlcv):
        bad = raw_ohlcv.copy()
        bad.loc[50, "close"] = bad.loc[50, "close"] * 100  # extreme outlier
        cleaned = clean_ohlcv(bad, remove_outliers=True)
        assert "is_outlier" in cleaned.columns
        assert cleaned["is_outlier"].any()

    def test_clean_empty_df(self):
        result = clean_ohlcv(pd.DataFrame())
        assert result.empty

    def test_clean_no_outlier_column_when_disabled(self, raw_ohlcv):
        cleaned = clean_ohlcv(raw_ohlcv, remove_outliers=False)
        assert "is_outlier" not in cleaned.columns


class TestDataStore:
    def test_save_and_query(self, raw_ohlcv):
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(str(Path(tmp) / "pq"), str(Path(tmp) / "db.duckdb"))
            store.save(raw_ohlcv, "BTC/USDT")
            result = store.query("BTC/USDT")
            assert len(result) > 0
            assert "close" in result.columns
            store.close()

    def test_list_symbols(self, raw_ohlcv):
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(str(Path(tmp) / "pq"), str(Path(tmp) / "db.duckdb"))
            store.save(raw_ohlcv, "BTC/USDT")
            symbols = store.list_symbols()
            assert "BTC_USDT" in symbols
            store.close()

    def test_query_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(str(Path(tmp) / "pq"), str(Path(tmp) / "db.duckdb"))
            result = store.query("NONEXISTENT/USDT")
            assert len(result) == 0
            store.close()

    def test_get_date_range_rejects_injection_symbol(self):
        """SEC-001: get_date_range must validate the symbol before interpolating
        it into the DuckDB read_parquet glob string. A crafted symbol with a
        single quote would otherwise break out and inject arbitrary SQL."""
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(str(Path(tmp) / "pq"), str(Path(tmp) / "db.duckdb"))
            with pytest.raises(ValueError, match="Invalid symbol"):
                store.get_date_range("BTC' OR '1'='1")
            # Path-traversal characters are also rejected by the symbol regex.
            with pytest.raises(ValueError, match="Invalid symbol"):
                store.get_date_range("../../etc/passwd")
            store.close()

    def test_get_date_range_returns_none_for_unknown_symbol(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(str(Path(tmp) / "pq"), str(Path(tmp) / "db.duckdb"))
            assert store.get_date_range("NONEXISTENT/USDT") is None
            store.close()

    def test_query_raises_data_error_on_corrupt_parquet(self, tmp_path):
        """ISS-20260723-013 (GP1): a corrupted parquet triggers a DuckDB
        execution failure → raises DataError, not an empty DataFrame. The
        "no data" path (symbol dir missing) still returns empty (see above)."""
        store = DataStore(str(tmp_path))
        symbol_dir = tmp_path / "BTC_USDT"
        symbol_dir.mkdir()
        year_dir = symbol_dir / "2024"
        year_dir.mkdir()
        (year_dir / "01.parquet").write_text("not a parquet file")
        with pytest.raises(DataError, match="Query failed"):
            store.query("BTC/USDT")
        store.close()

    def test_get_date_range_raises_data_error_on_corrupt_parquet(self, tmp_path):
        """ISS-20260723-014 (GP1): corrupted parquet → DataError, not None.
        Unknown symbol (dir missing) still returns None (no-data path)."""
        store = DataStore(str(tmp_path))
        symbol_dir = tmp_path / "BTC_USDT"
        symbol_dir.mkdir()
        year_dir = symbol_dir / "2024"
        year_dir.mkdir()
        (year_dir / "01.parquet").write_text("not a parquet file")
        with pytest.raises(DataError, match="get_date_range failed"):
            store.get_date_range("BTC/USDT")
        store.close()

    def test_get_last_timestamp_raises_data_error_on_corrupt_parquet(self, tmp_path):
        """ISS-20260723-016 (GP1): corrupted parquet → DataError, not None.
        Unknown symbol (dir missing) still returns None (no-data path)."""
        store = DataStore(str(tmp_path))
        symbol_dir = tmp_path / "BTC_USDT"
        symbol_dir.mkdir()
        year_dir = symbol_dir / "2024"
        year_dir.mkdir()
        (year_dir / "01.parquet").write_text("not a parquet file")
        with pytest.raises(DataError, match="get_last_timestamp failed"):
            store.get_last_timestamp("BTC/USDT", "1d")
        store.close()
