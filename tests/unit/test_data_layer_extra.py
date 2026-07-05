"""Tests for data layer uncovered paths — store.py, fetcher.py, feature_store.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from quantflow.common.exceptions import GatewayConnectionError
from quantflow.data.feature_store import FeatureStore
from quantflow.data.store import DataStore

# ---------------------------------------------------------------------------
# DataStore — query exception path, _read_parquet_source edge cases
# ---------------------------------------------------------------------------


class TestDataStoreQueryException:
    def test_query_returns_empty_on_exception(self, tmp_path):
        """Line 136-138: query catches exception → returns empty DataFrame."""
        store = DataStore(str(tmp_path))
        # query on non-existent symbol triggers exception path
        result = store.query(symbol="NONEXIST/USDT")
        assert isinstance(result, pd.DataFrame)

    def test_list_symbols_empty(self, tmp_path):
        """list_symbols with no subdirectories."""
        store = DataStore(str(tmp_path))
        assert store.list_symbols() == []

    def test_list_symbols_with_dirs(self, tmp_path):
        """list_symbols finds symbol directories."""
        (tmp_path / "BTC_USDT").mkdir()
        (tmp_path / "ETH_USDT").mkdir()
        # Create a file (not dir) to verify it's skipped
        (tmp_path / "readme.txt").write_text("hello")
        store = DataStore(str(tmp_path))
        symbols = store.list_symbols()
        assert "BTC_USDT" in symbols
        assert "ETH_USDT" in symbols
        assert "readme.txt" not in symbols

    def test_read_parquet_source_no_paths_no_start_end(self, tmp_path):
        """Lines 183-185: no paths and no start/end → glob pattern source."""
        store = DataStore(str(tmp_path))
        symbol_dir = tmp_path / "TEST_USDT"
        symbol_dir.mkdir()
        # No parquet files → _candidate_paths returns [] → glob fallback
        source = store._read_parquet_source("TEST_USDT")
        assert source is not None
        assert "**/*.parquet" in source

    def test_read_parquet_source_no_paths_with_start_end(self, tmp_path):
        """No paths with start/end filters → returns None."""
        store = DataStore(str(tmp_path))
        symbol_dir = tmp_path / "TEST_USDT"
        symbol_dir.mkdir()
        source = store._read_parquet_source("TEST_USDT", start=1000, end=2000)
        assert source is None

    def test_read_parquet_source_with_paths(self, tmp_path):
        """Paths found → escaped list source."""
        store = DataStore(str(tmp_path))
        symbol_dir = tmp_path / "TEST_USDT"
        year_dir = symbol_dir / "2024"
        year_dir.mkdir(parents=True)
        df = pd.DataFrame({"close": [100.0], "timestamp": [1700000000000]})
        df.to_parquet(year_dir / "01.parquet")
        source = store._read_parquet_source("TEST_USDT")
        assert source is not None
        assert "01.parquet" in source

    def test_read_parquet_source_nonexistent_dir(self, tmp_path):
        """Nonexistent symbol directory → returns None."""
        store = DataStore(str(tmp_path))
        source = store._read_parquet_source("NONEXIST_USDT")
        assert source is None


# ---------------------------------------------------------------------------
# Fetcher — connect exception close path
# ---------------------------------------------------------------------------


class TestFetcherConnectCloseException:
    @pytest.mark.asyncio
    async def test_connect_closes_exchange_on_failure(self):
        """Lines 55-56: On connection failure, exchange.close() is called."""
        from quantflow.common.config import DataConfig
        from quantflow.data.fetcher import DataFetcher

        mock_exchange = AsyncMock()
        mock_exchange.load_markets = AsyncMock(side_effect=RuntimeError("market load failed"))
        mock_exchange.close = AsyncMock()

        with patch("quantflow.data.fetcher.ccxt") as mock_ccxt:
            mock_ccxt.okx = MagicMock(return_value=mock_exchange)
            fetcher = DataFetcher(DataConfig())
            with pytest.raises(GatewayConnectionError, match="Failed to connect"):
                await fetcher.connect()

        # close() should have been attempted
        mock_exchange.close.assert_awaited()
        assert fetcher._exchange is None

    @pytest.mark.asyncio
    async def test_connect_closes_even_if_close_fails(self):
        """Lines 55-56: If exchange.close() also fails, still raises GatewayConnectionError."""
        from quantflow.common.config import DataConfig
        from quantflow.data.fetcher import DataFetcher

        mock_exchange = AsyncMock()
        mock_exchange.load_markets = AsyncMock(side_effect=RuntimeError("market load failed"))
        mock_exchange.close = AsyncMock(side_effect=RuntimeError("close also failed"))

        with patch("quantflow.data.fetcher.ccxt") as mock_ccxt:
            mock_ccxt.okx = MagicMock(return_value=mock_exchange)
            fetcher = DataFetcher(DataConfig())
            with pytest.raises(GatewayConnectionError, match="Failed to connect"):
                await fetcher.connect()

        # exchange should be set to None even when close fails
        assert fetcher._exchange is None


# ---------------------------------------------------------------------------
# FeatureStore — timestamp path, _candidate_parquet_files, _timestamp_period
# ---------------------------------------------------------------------------


class TestFeatureStoreEdgeCases:
    def test_save_features_with_timestamp_column(self, tmp_path):
        """Line 64-67: save_features() with timestamp column (no datetime)."""
        store = FeatureStore(str(tmp_path))
        df = pd.DataFrame(
            {
                "timestamp": [1700000000000, 1700086400000],
                "feat1": [1.0, 2.0],
                "feat2": [3.0, 4.0],
            }
        )
        store.save_features("TEST/USDT", df)
        # Verify parquet files created
        symbol_dir = tmp_path / "features" / "TEST_USDT"
        assert symbol_dir.exists()

    def test_save_features_requires_datetime_or_timestamp(self, tmp_path):
        """Line 69: ValueError when neither datetime nor timestamp column."""
        store = FeatureStore(str(tmp_path))
        df = pd.DataFrame({"feat1": [1.0], "feat2": [2.0]})
        with pytest.raises(ValueError, match=r"datetime.*timestamp"):
            store.save_features("TEST/USDT", df)

    def test_load_features_legacy_parquet(self, tmp_path):
        """Line 121: legacy features.parquet file used when present."""
        store = FeatureStore(str(tmp_path))
        symbol_dir = tmp_path / "features" / "TEST_USDT"
        symbol_dir.mkdir(parents=True)
        df = pd.DataFrame({"feat1": [1.0], "timestamp": [1700000000000]})
        df.to_parquet(symbol_dir / "features.parquet")
        result = store.load_features("TEST/USDT")
        assert result is not None
        assert len(result) == 1

    def test_load_features_nonexistent_symbol(self, tmp_path):
        """Line 123: load_features returns empty DataFrame when symbol dir doesn't exist."""
        store = FeatureStore(str(tmp_path))
        result = store.load_features("NONEXIST/USDT")
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_load_features_no_candidate_paths(self, tmp_path):
        """Line 127-128: load_features returns empty when no parquet files match."""
        store = FeatureStore(str(tmp_path))
        symbol_dir = tmp_path / "features" / "TEST_USDT"
        symbol_dir.mkdir(parents=True)
        # Empty dir → no parquet files
        result = store.load_features("TEST/USDT", start=9999999999999)
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_timestamp_period_none_lower(self):
        """_timestamp_period with None and lower_bound=True → (0, 1)."""
        result = FeatureStore._timestamp_period(None, lower_bound=True)
        assert result == (0, 1)

    def test_timestamp_period_none_upper(self):
        """_timestamp_period with None and lower_bound=False → (9999, 12)."""
        result = FeatureStore._timestamp_period(None, lower_bound=False)
        assert result == (9999, 12)

    def test_timestamp_period_with_value(self):
        """_timestamp_period with a real timestamp."""
        # 2024-01-01 00:00:00 UTC = 1704067200000 ms
        result = FeatureStore._timestamp_period(1704067200000, lower_bound=True)
        assert result[0] == 2024
        assert result[1] == 1

    def test_path_period(self):
        """_path_period extracts (year, month) from path structure."""
        path = Path("/data/TEST_USDT/2024/06.parquet")
        result = FeatureStore._path_period(path)
        assert result == (2024, 6)

    def test_save_and_load_features_roundtrip(self, tmp_path):
        """Full save → load roundtrip with datetime column."""
        store = FeatureStore(str(tmp_path))
        dates = pd.date_range("2024-01-01", periods=10, freq="D", tz="UTC")
        df = pd.DataFrame(
            {
                "datetime": dates,
                "feat1": np.arange(10, dtype=float),
                "feat2": np.arange(10, 20, dtype=float),
            }
        )
        store.save_features("TEST/USDT", df)
        result = store.load_features("TEST/USDT")
        assert result is not None
        assert len(result) == 10
        assert "feat1" in result.columns
