"""Tests for feature_store module — including API mismatch fix verification."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.data.feature_store import FeatureStore
from quantflow.data.store import DataStore
from quantflow.indicators.engine import IndicatorEngine


class _FakeIndicatorComputer:
    """Stub implementing IndicatorComputer protocol for testing."""

    def compute_all(
        self, df: pd.DataFrame, indicator_names: list[str] | None = None
    ) -> pd.DataFrame:
        result_df = df.copy()
        result_df["fake_indicator"] = 0.0
        return result_df


class TestIndicatorEngineAPI:
    """Verify IndicatorEngine has the methods that FeatureStore expects."""

    def test_batch_calculate_exists(self):
        engine = IndicatorEngine()
        assert hasattr(engine, "batch_calculate")

    def test_calculate_alias_exists(self):
        engine = IndicatorEngine()
        assert hasattr(engine, "calculate")
        assert engine.calculate == engine.batch_calculate

    def test_batch_calculate_accepts_single_df(self):
        engine = IndicatorEngine()
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        df = pd.DataFrame(
            {
                "open": np.random.randn(100).cumsum() + 100,
                "high": np.random.randn(100).cumsum() + 101,
                "low": np.random.randn(100).cumsum() + 99,
                "close": np.random.randn(100).cumsum() + 100,
                "volume": np.random.randint(100, 10000, 100),
            },
            index=dates,
        )
        result = engine.batch_calculate(df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(df)

    def test_batch_calculate_returns_indicator_columns(self):
        engine = IndicatorEngine()
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        df = pd.DataFrame(
            {
                "open": np.random.randn(100).cumsum() + 100,
                "high": np.random.randn(100).cumsum() + 101,
                "low": np.random.randn(100).cumsum() + 99,
                "close": np.random.randn(100).cumsum() + 100,
                "volume": np.random.randint(100, 10000, 100),
            },
            index=dates,
        )
        result = engine.batch_calculate(df)
        assert "sma_20" in result.columns
        assert "rsi_14" in result.columns


class TestFeatureStore:
    """Test FeatureStore with fixed IndicatorEngine API."""

    @pytest.fixture
    def store_and_raw(self, tmp_path):
        raw_dir = tmp_path / "raw"
        feat_dir = tmp_path / "features"
        raw_dir.mkdir()
        feat_dir.mkdir()

        raw_store = DataStore(str(raw_dir))

        dates = pd.date_range("2024-01-01", periods=200, freq="D")
        df = pd.DataFrame(
            {
                "timestamp": [int(d.timestamp() * 1000) for d in dates],
                "open": np.random.randn(200).cumsum() + 50000,
                "high": np.random.randn(200).cumsum() + 50100,
                "low": np.random.randn(200).cumsum() + 49900,
                "close": np.random.randn(200).cumsum() + 50000,
                "volume": np.random.randint(100, 10000, 200),
            }
        )
        raw_store.save(df, "BTC/USDT")

        fs = FeatureStore(str(feat_dir), indicator_computer=_FakeIndicatorComputer())
        return fs, raw_store

    def test_compute_features_returns_dataframe(self, store_and_raw):
        fs, raw_store = store_and_raw
        ts = 1700000000000
        result = fs.compute_features("BTC/USDT", ts, [], raw_store)
        assert isinstance(result, pd.DataFrame)

    def test_compute_features_no_raw_store_raises(self, tmp_path):
        fs = FeatureStore(str(tmp_path), indicator_computer=_FakeIndicatorComputer())
        with pytest.raises(ValueError, match="raw_store is required"):
            fs.compute_features("BTC/USDT", 0, [])

    def test_compute_features_empty_result_for_no_data(self, store_and_raw):
        fs, raw_store = store_and_raw
        result = fs.compute_features("BTC/USDT", 0, [], raw_store)
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_save_and_load_features(self, store_and_raw):
        fs, raw_store = store_and_raw
        ts = 1700000000000
        features = fs.compute_features("BTC/USDT", ts, [], raw_store)
        if not features.empty:
            fs.save_features("BTC/USDT", features)
            loaded = fs.load_features("BTC/USDT")
            assert isinstance(loaded, pd.DataFrame)
            assert len(loaded) > 0

    def test_load_features_nonexistent_symbol(self, tmp_path):
        fs = FeatureStore(str(tmp_path))
        result = fs.load_features("NONEXIST/USDT")
        assert result.empty

    def test_save_features_ignores_empty_frame(self, tmp_path):
        fs = FeatureStore(str(tmp_path))

        fs.save_features("BTC/USDT", pd.DataFrame())

        assert not list((tmp_path / "features" / "BTC_USDT").glob("**/*.parquet"))

    def test_save_features_with_datetime_deduplicates_and_sorts(self, tmp_path):
        fs = FeatureStore(str(tmp_path))
        features = pd.DataFrame(
            {
                "timestamp": [1704153600000, 1704067200000, 1704153600000],
                "datetime": pd.to_datetime(
                    ["2024-01-02T00:00:00Z", "2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z"],
                    utc=True,
                ),
                "value": [2.0, 1.0, 99.0],
            }
        )

        fs.save_features("BTC/USDT", features)
        saved = pd.read_parquet(tmp_path / "features" / "BTC_USDT" / "2024" / "01.parquet")

        assert list(saved["timestamp"]) == [1704067200000, 1704153600000]
        assert list(saved["year"]) == [2024, 2024]
        assert list(saved["month"]) == [1, 1]

    def test_save_features_without_timestamp_derives_timestamp_from_datetime(self, tmp_path):
        fs = FeatureStore(str(tmp_path))
        features = pd.DataFrame(
            {
                "datetime": pd.to_datetime(
                    ["2024-01-02T00:00:00Z", "2024-01-01T00:00:00Z"],
                    utc=True,
                ),
                "value": [2.0, 1.0],
            }
        )

        fs.save_features("BTC/USDT", features)
        loaded = fs.load_features("BTC/USDT")

        assert list(loaded["timestamp"]) == [1704067200000, 1704153600000]
        assert list(loaded["value"]) == [1.0, 2.0]

    def test_save_features_with_timestamp_column_and_filtered_load(self, tmp_path):
        fs = FeatureStore(str(tmp_path))
        features = pd.DataFrame(
            {
                "timestamp": [1704067200000, 1704153600000, 1704240000000],
                "value": [1.0, 2.0, 3.0],
            }
        )

        fs.save_features("BTC/USDT", features)
        loaded = fs.load_features("BTC/USDT", start=1704153600000, end=1704240000000)

        assert list(loaded["timestamp"]) == [1704153600000, 1704240000000]
        assert list(loaded["value"]) == [2.0, 3.0]

    def test_load_features_supports_legacy_single_file_layout(self, tmp_path):
        fs = FeatureStore(str(tmp_path))
        symbol_dir = tmp_path / "features" / "BTC_USDT"
        symbol_dir.mkdir(parents=True)
        legacy = pd.DataFrame(
            {
                "timestamp": [1704067200000, 1704153600000],
                "value": [1.0, 2.0],
            }
        )
        legacy.to_parquet(symbol_dir / "features.parquet", index=False)

        loaded = fs.load_features("BTC/USDT", start=1704153600000)

        assert list(loaded["timestamp"]) == [1704153600000]
        assert list(loaded["value"]) == [2.0]

    def test_load_features_returns_empty_on_query_failure(self, tmp_path, monkeypatch):
        """ISS-20260723-014 (GP1 fail-silent): a DuckDB execution failure
        during load_features now raises DataError — previously returned an
        empty DataFrame indistinguishable from "no data". The "no data"
        path (source None) still returns an empty DataFrame."""
        import pytest

        from quantflow.common.exceptions import DataError

        fs = FeatureStore(str(tmp_path))
        features = pd.DataFrame({"timestamp": [1704067200000], "value": [1.0]})
        fs.save_features("BTC/USDT", features)

        class BrokenDB:
            def query(self, sql: str):
                raise RuntimeError("duckdb unavailable")

        monkeypatch.setattr(fs, "_db", BrokenDB())

        with pytest.raises(DataError, match="load_features failed"):
            fs.load_features("BTC/USDT")

    def test_close(self, tmp_path):
        fs = FeatureStore(str(tmp_path))
        fs.close()
