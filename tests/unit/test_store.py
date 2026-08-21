"""Unit tests for DataStore meta extensions (T-s2-02).

Key scenarios (plan test_plan):
- Partitioned save/query round-trip (funding + OI)
- Path traversal rejected on write path (REV-008)
- Incremental replay re-save keep='last' dedupe (no row inflation)
- get_last_meta_timestamp fail-silent distinction (None vs DataError)
- Point-in-time truncation via end= (no future leakage)
"""

from __future__ import annotations

import pandas as pd
import pytest

from quantflow.common.exceptions import DataError
from quantflow.data.store import DataStore

SYMBOL = "BTC/USDT"


def _funding_df(n_rows: int, start_ts: int = 1_700_000_000_000, step_ms: int = 8 * 3600_000):
    return pd.DataFrame(
        {
            "timestamp": [start_ts + i * step_ms for i in range(n_rows)],
            "funding_rate": [0.0001 * (i % 5 + 1) for i in range(n_rows)],
            "realized_rate": [0.0001 * (i % 5 + 1) for i in range(n_rows)],
            "funding_time": [start_ts + i * step_ms for i in range(n_rows)],
        }
    )


def _oi_df(n_rows: int, start_ts: int = 1_700_000_000_000, step_ms: int = 3600_000):
    return pd.DataFrame(
        {
            "timestamp": [start_ts + i * step_ms for i in range(n_rows)],
            "open_interest": [1000.0 + i for i in range(n_rows)],
            "open_interest_ccy": [900.0 + i for i in range(n_rows)],
            "open_interest_usd": [40_000_000.0 + i for i in range(n_rows)],
        }
    )


@pytest.fixture
def store(tmp_path):
    ds = DataStore(str(tmp_path / "parquet"), ":memory:")
    yield ds
    ds.close()


class TestMetaRoundTrip:
    def test_funding_save_query_round_trip_90_days(self, store: DataStore):
        """90 days x 8h = 270 rows saved and queried back, ordered."""
        df = _funding_df(270)
        store.save_funding_rates(df, SYMBOL)

        out = store.query_funding_rates(SYMBOL)

        assert len(out) == 270
        assert out["timestamp"].is_monotonic_increasing
        assert {"timestamp", "funding_rate", "realized_rate", "funding_time"} <= set(out.columns)

    def test_oi_save_query_round_trip(self, store: DataStore):
        df = _oi_df(100)
        store.save_open_interest(df, SYMBOL)

        out = store.query_open_interest(SYMBOL)

        assert len(out) == 100
        assert out["open_interest"].iloc[-1] == pytest.approx(1099.0)

    def test_meta_dirs_do_not_pollute_ohlcv_listing(self, store: DataStore):
        """meta_* top-level dirs are excluded from list_symbols/get_date_range."""
        store.save_funding_rates(_funding_df(10), SYMBOL)
        assert "meta_funding_rate" not in store.list_symbols()
        assert store.get_date_range(SYMBOL) is None  # no OHLCV saved for symbol


class TestWritePathSecurity:
    def test_path_traversal_symbol_rejected(self, store: DataStore):
        with pytest.raises((ValueError, DataError)):
            store.save_funding_rates(_funding_df(3), "../../evil")
        with pytest.raises((ValueError, DataError)):
            store.save_open_interest(_oi_df(3), "evil; DROP TABLE x")

    def test_missing_required_columns_rejected(self, store: DataStore):
        bad = pd.DataFrame({"timestamp": [1], "funding_rate": [0.0]})
        with pytest.raises(DataError):
            store.save_funding_rates(bad, SYMBOL)


class TestIncrementalDedupe:
    def test_replay_same_timestamps_no_inflation(self, store: DataStore):
        """Re-saving overlapping timestamps dedupes keep='last'."""
        df = _funding_df(20)
        store.save_funding_rates(df, SYMBOL)
        store.save_funding_rates(df, SYMBOL)  # exact replay

        out = store.query_funding_rates(SYMBOL)
        assert len(out) == 20
        assert out["timestamp"].is_unique

    def test_append_only_fast_path_newer_rows(self, store: DataStore):
        first = _funding_df(10)
        last_ts = int(first["timestamp"].max())
        second = _funding_df(5, start_ts=last_ts + 8 * 3600_000)
        store.save_funding_rates(first, SYMBOL)
        store.save_funding_rates(second, SYMBOL)

        out = store.query_funding_rates(SYMBOL)
        assert len(out) == 15
        assert out["timestamp"].is_monotonic_increasing


class TestGetLastMetaTimestamp:
    def test_no_data_returns_none(self, store: DataStore):
        assert store.get_last_meta_timestamp(SYMBOL, "funding_rate") is None
        assert store.get_last_meta_timestamp(SYMBOL, "open_interest") is None

    def test_returns_max_timestamp_after_save(self, store: DataStore):
        df = _funding_df(12)
        store.save_funding_rates(df, SYMBOL)
        assert store.get_last_meta_timestamp(SYMBOL, "funding_rate") == int(df["timestamp"].max())

    def test_invalid_data_type_rejected(self, store: DataStore):
        with pytest.raises(ValueError):
            store.get_last_meta_timestamp(SYMBOL, "ohlcv; DROP")

    def test_corrupt_parquet_raises_data_error(self, store: DataStore, tmp_path):
        """Corrupt file under a valid meta dir -> DataError (not None)."""
        corrupt_dir = tmp_path / "parquet" / "meta_funding_rate" / "BTC_USDT" / "2024"
        corrupt_dir.mkdir(parents=True)
        (corrupt_dir / "01.parquet").write_bytes(b"not a parquet file")
        with pytest.raises(DataError):
            store.get_last_meta_timestamp(SYMBOL, "funding_rate")


class TestPointInTimeTruncation:
    def test_end_bound_excludes_future_rows(self, store: DataStore):
        """Point-in-time correctness: query(end=T) never returns rows > T."""
        df = _funding_df(30)
        store.save_funding_rates(df, SYMBOL)
        cutoff = int(df["timestamp"].iloc[14])

        out = store.query_funding_rates(SYMBOL, end=cutoff)

        assert len(out) == 15
        assert int(out["timestamp"].max()) <= cutoff

    def test_start_bound_excludes_old_rows(self, store: DataStore):
        df = _oi_df(30)
        store.save_open_interest(df, SYMBOL)
        lower = int(df["timestamp"].iloc[10])

        out = store.query_open_interest(SYMBOL, start=lower)

        assert int(out["timestamp"].min()) >= lower
        assert len(out) == 20

    def test_query_empty_symbol_returns_column_contract(self, store: DataStore):
        out = store.query_funding_rates("ETH/USDT")
        assert out.empty
        assert list(out.columns) == [
            "timestamp",
            "funding_rate",
            "realized_rate",
            "funding_time",
        ]
