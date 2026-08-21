"""Coverage closure: store.py + trades_store.py + mtf_aligner.py + cleaner.py + feature_store.py."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from quantflow.common.exceptions import DataError
from quantflow.data.cleaner import (
    _detect_outliers,
    clean_ohlcv,
    validate_no_future_leak,
)
from quantflow.data.feature_store import FeatureStore
from quantflow.data.mtf_aligner import MTFAligner, _infer_period
from quantflow.data.multi_symbol_trades import (
    build_multi_symbol_trades_ingest,
)
from quantflow.data.store import DataStore
from quantflow.data.trades_store import (
    TradesStore,
    build_cvd_feature_frame,
    save_cvd_features,
)

# ===========================================================================
# store.py
# ===========================================================================


def test_store_save_datetime64_timestamp_and_meta_validation(tmp_path) -> None:
    store = DataStore(str(tmp_path / "data"))
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2024-01-01", "2024-01-02"], utc=True),
            "open": [1.0, 2.0],
            "high": [2.0, 3.0],
            "low": [0.5, 1.5],
            "close": [1.5, 2.5],
            "volume": [10.0, 20.0],
        }
    )
    store.save(df, "BTC/USDT")  # 90-95 datetime64 -> ms int normalization
    with pytest.raises(ValueError):
        store._save_meta(df, "BTC/USDT", "bogus")  # 185
    store._save_meta(pd.DataFrame(), "BTC/USDT", "funding_rate")  # 189 empty -> return
    with pytest.raises(ValueError):
        store._query_meta("bogus", "BTC/USDT", None, None)  # 225


def test_store_meta_query_filter_and_storage_failure(tmp_path) -> None:
    store = DataStore(str(tmp_path / "data"))
    funding = pd.DataFrame(
        {
            "timestamp": [1_704_067_200_000, 1_704_070_800_000],
            "funding_rate": [0.0001, 0.0002],
            "realized_rate": [0.0001, 0.0002],
            "funding_time": [1_704_067_200_000, 1_704_070_800_000],
        }
    )
    store.save_funding_rates(funding, "BTC/USDT")
    df = store.query_funding_rates("BTC/USDT", start=1_704_069_000_000, end=1_704_070_800_000)
    assert df["timestamp"].tolist() == [1_704_070_800_000]

    # Corrupt the parquet -> DuckDB read fails -> DataError (252-256).
    store.save_funding_rates(funding, "ETH/USDT")
    meta_dir = store._parquet_dir / "meta_funding_rate" / "ETH_USDT"
    corrupt = next(meta_dir.glob("*/*.parquet"))
    corrupt.write_text("this is not parquet")
    with pytest.raises(DataError):
        store.query_funding_rates("ETH/USDT")


def test_store_no_data_fallthrough_paths(tmp_path) -> None:
    store = DataStore(str(tmp_path / "data"))

    # Empty parquet with the right columns -> MAX() returns NULL -> None (290/380/428).
    symbol_dir = store._parquet_dir / "SOL_USDT" / "2024"
    symbol_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=["timestamp", "timeframe"]).to_parquet(
        symbol_dir / "01.parquet", index=False
    )
    assert store.get_date_range("SOL/USDT") is None  # 380
    assert store.get_last_timestamp("SOL/USDT", "1h") is None  # 428

    meta_dir = store._parquet_dir / "meta_funding_rate" / "SOL_USDT" / "2024"
    meta_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=["timestamp"]).to_parquet(meta_dir / "01.parquet", index=False)
    assert store.get_last_meta_timestamp("SOL/USDT", "funding_rate") is None  # 290

    # _candidate_paths with no filters (direct static call, 472).
    assert isinstance(DataStore._candidate_paths(Path("."), None, None), list)


# ===========================================================================
# trades_store.py
# ===========================================================================


def test_trades_store_save_edge_cases(tmp_path) -> None:
    store = TradesStore(str(tmp_path / "trades"))
    assert store.save_trades("BTC/USDT", pd.DataFrame()) == 0  # 39
    assert store.save_trades("BTC/USDT", None) == 0  # 39
    with pytest.raises(DataError):
        store.save_trades("BTC/USDT", pd.DataFrame({"timestamp": [1], "price": [2.0]}))  # 44
    bad = pd.DataFrame({"timestamp": [1], "price": ["nope"], "amount": [3.0], "side": ["buy"]})
    assert store.save_trades("BTC/USDT", bad) == 0  # 51 empty after dropna


def test_trades_store_load_paths(tmp_path) -> None:
    store = TradesStore(str(tmp_path / "trades"))
    assert store.load_trades("BTC/USDT").empty  # 82 root missing

    frame = pd.DataFrame(
        {
            "timestamp": [100, 200, 300],
            "price": [1.0, 2.0, 3.0],
            "amount": [0.5, 0.6, 0.7],
            "side": ["buy", "sell", "buy"],
        }
    )
    store.save_trades("BTC/USDT", frame)

    (store._base / "ETH_USDT").mkdir(parents=True, exist_ok=True)
    assert store.load_trades("ETH/USDT").empty  # 85 no parquet files

    sol_dir = store._base / "SOL_USDT" / "year=2024"
    sol_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"price": [1.0]}).to_parquet(sol_dir / "month=01.parquet")
    assert store.load_trades("SOL/USDT").empty  # 89 no timestamp column

    df = store.load_trades("BTC/USDT", start=200, end=200)
    assert df["timestamp"].tolist() == [200]  # 92 + 94 filters


def test_build_cvd_feature_frame_paths() -> None:
    assert build_cvd_feature_frame(None).empty  # 116
    assert build_cvd_feature_frame(pd.DataFrame()).empty  # 116
    with pytest.raises(DataError):
        build_cvd_feature_frame(pd.DataFrame({"close": [1.0]}))  # 120

    # No close/volume -> cvd NaN + source "empty" (148-149) and helper-col loop (154->153).
    odd = build_cvd_feature_frame(pd.DataFrame({"timestamp": [1], "open": [1.0]}))
    assert odd["cvd_source"].tolist() == ["empty"] and pd.isna(odd["cvd"].iloc[0])

    proxy = build_cvd_feature_frame(
        pd.DataFrame({"timestamp": [1], "close": [1.0], "volume": [2.0]})
    )
    assert proxy["cvd_source"].tolist() == ["proxy"]

    trades = pd.DataFrame(
        {"timestamp": [1, 2], "price": [10.0, 11.0], "amount": [1.0, 1.0], "side": ["buy", "sell"]}
    )
    ohlcv = pd.DataFrame({"timestamp": [1, 2], "close": [10.0, 11.0], "volume": [5.0, 5.0]})
    out = build_cvd_feature_frame(ohlcv, trades)
    assert out["cvd_source"].tolist() == ["trades", "trades"]
    assert out["cvd"].tolist() == [1.0, 0.0]  # cumulative signed volume: buy +1, sell -1


def test_save_cvd_features_skip_empty(tmp_path) -> None:
    fs = FeatureStore(str(tmp_path / "feat"))
    frame = save_cvd_features(fs, "BTC/USDT", pd.DataFrame())
    assert frame.empty  # 169->171 skip save
    frame2 = save_cvd_features(
        fs, "BTC/USDT", pd.DataFrame({"timestamp": [1], "close": [1.0], "volume": [2.0]})
    )
    assert not frame2.empty  # 169-170 save called


# ===========================================================================
# mtf_aligner.py
# ===========================================================================


def test_infer_period_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _infer_period(pd.DatetimeIndex([])) is None  # 41-42
    idx = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
    assert _infer_period(idx) == pd.Timedelta(hours=1)  # 43-44 declared freq
    idx2 = pd.to_datetime(["2024-01-01 00:00", "2024-01-01 01:00", "2024-01-01 02:00"])
    assert _infer_period(idx2) is not None  # 45-48 infer_freq
    idx3 = pd.to_datetime(
        ["2024-01-01 00:00", "2024-01-01 01:00", "2024-01-01 02:00", "2024-01-01 04:00"]
    )
    assert _infer_period(idx3) == pd.Timedelta(hours=1)  # 51-54 median of diffs (1h,1h,2h)
    assert _infer_period(pd.DatetimeIndex([pd.NaT, pd.NaT, pd.NaT])) is None  # 52-53 empty diffs

    # infer_freq returns junk -> to_offset raises -> except path (49-50).
    monkeypatch.setattr(pd, "infer_freq", lambda index: "bogus-freq")
    assert _infer_period(idx2) == pd.Timedelta(hours=1)


def test_mtf_aligner_index_helpers() -> None:
    a = MTFAligner()
    primary_naive = pd.DataFrame(
        {"close": [1.0, 2.0]}, index=pd.to_datetime(["2024-01-01", "2024-01-02"])
    )
    idx = a._create_aligned_index(pd.DataFrame(), primary_naive)
    assert idx.tz is not None  # 174-176 tz-naive primary

    primary_aware = pd.DataFrame(
        {"close": [1.0, 2.0]}, index=pd.to_datetime(["2024-01-01", "2024-01-02"]).tz_localize("UTC")
    )
    idx2 = a._create_aligned_index(pd.DataFrame(), primary_aware)
    assert idx2.tz is not None  # 174-176 tz-aware primary

    # _reindex_to_utc with a degenerate (<2 bar) index -> period None (211->214).
    single = pd.DataFrame({"close": [1.0]}, index=pd.to_datetime(["2024-01-01"]))
    out = a._reindex_to_utc(single, primary_aware.index)
    assert out is not None

    # _fallback_align with everything empty -> both index sources skipped (231->235).
    fb = a._fallback_align({}, ["1W", "4H", "1H"])
    assert fb.aligned_index.empty

    # _fallback_align with tz-aware minor (230 ternary False) and tz-naive minor (True).
    minor_aware = pd.DataFrame(
        {"close": [1.0, 2.0]},
        index=pd.to_datetime(["2024-01-01", "2024-01-02"]).tz_localize("UTC"),
    )
    fb2 = a._fallback_align(
        {"x": pd.DataFrame(), "y": pd.DataFrame(), "z": minor_aware},
        ["1W", "4H", "1H"],
    )
    assert len(fb2.aligned_index) == 2
    minor_naive = pd.DataFrame(
        {"close": [1.0, 2.0]}, index=pd.to_datetime(["2024-01-01", "2024-01-02"])
    )
    fb3 = a._fallback_align(
        {"x": pd.DataFrame(), "y": pd.DataFrame(), "z": minor_naive},
        ["1W", "4H", "1H"],
    )
    assert len(fb3.aligned_index) == 2


# ===========================================================================
# multi_symbol_trades.py
# ===========================================================================


def test_multi_symbol_coordinator_mutation_and_stats(tmp_path) -> None:
    store = TradesStore(str(tmp_path / "trades"))

    async def fetch(symbol: str, limit: int = 100) -> pd.DataFrame:
        return pd.DataFrame({"timestamp": [1], "price": [2.0], "amount": [3.0], "side": ["buy"]})

    coord = build_multi_symbol_trades_ingest(
        store, fetch_trades=fetch, symbols=["BTC/USDT", "ETH/USDT"]
    )
    assert coord.per_symbol_batches == {"BTC/USDT": 0, "ETH/USDT": 0}
    coord.add_symbol("BTC/USDT")  # 48->exit already present
    coord.add_symbol("SOL/USDT")  # 49-52
    assert coord.loop._symbols == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    coord.remove_symbol("ETH/USDT")  # 55-57
    coord.remove_symbol("NOPE")  # remove of absent symbol
    assert coord.loop._symbols == ["BTC/USDT", "SOL/USDT"]
    assert coord.stats()["symbols"] == ["BTC/USDT", "SOL/USDT"]
    with pytest.raises(ValueError):
        build_multi_symbol_trades_ingest(store, fetch_trades=fetch, symbols=[])  # 91


@pytest.mark.asyncio
async def test_multi_symbol_coordinator_lifecycle(tmp_path) -> None:
    store = TradesStore(str(tmp_path / "trades"))

    async def fetch(symbol: str, limit: int = 100) -> pd.DataFrame:
        return pd.DataFrame({"timestamp": [1], "price": [2.0], "amount": [3.0], "side": ["buy"]})

    coord = build_multi_symbol_trades_ingest(store, fetch_trades=fetch, symbols=["BTC/USDT"])
    total = await coord.poll_once()  # _cb -> c._on_batch
    assert total == 1
    assert coord.per_symbol_batches["BTC/USDT"] == 1
    assert coord.per_symbol_rows["BTC/USDT"] == 1
    task = coord.start()  # 63
    assert task is not None
    await coord.stop()  # 66
    assert coord.stats()["rows_written"] == 1


# ===========================================================================
# cleaner.py
# ===========================================================================


def test_clean_ohlcv_edge_columns_and_branches() -> None:
    # No timestamp/datetime columns at all -> sort branches 48->52 and 57->59.
    df = pd.DataFrame(
        {"open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5], "volume": [10.0]}
    )
    out = clean_ohlcv(df, validate_no_future_leak=False, remove_outliers=False)
    assert out["close"].tolist() == [1.5]

    # Missing one OHLC column -> OHLC-relationship check skipped (89->108).
    df2 = pd.DataFrame({"timestamp": [1, 2], "close": [1.0, 2.0], "volume": [1.0, 2.0]})
    out2 = clean_ohlcv(df2, validate_no_future_leak=False, remove_outliers=False)
    assert out2["close"].tolist() == [1.0, 2.0]

    # No duplicates -> before == after (69->71).
    df3 = pd.DataFrame({"timestamp": [1, 2], "close": [1.0, 2.0]})
    out3 = clean_ohlcv(df3, validate_no_future_leak=False, remove_outliers=False)
    assert len(out3) == 2

    # Unknown fill_method with NaN -> elif False edge (69->71... wait, line 69 branch).
    df4 = pd.DataFrame({"timestamp": [1, 2], "open": [1.0, None], "close": [1.0, 2.0]})
    out4 = clean_ohlcv(
        df4, fill_method="weird", validate_no_future_leak=False, remove_outliers=False
    )
    assert out4["open"].isna().sum() == 1

    # Duplicate + NaN fill + outlier + invalid OHLC exercised for good measure.
    df5 = pd.DataFrame(
        {
            "timestamp": [1, 1, 2],
            "open": [10.0, 10.0, None],
            "high": [5.0, 5.0, 20.0],
            "low": [1.0, 1.0, 15.0],
            "close": [10.0, 10.0, 20.0],
            "volume": [1.0, 1.0, None],
        }
    )
    out5 = clean_ohlcv(df5, validate_no_future_leak=False)
    assert len(out5) == 2


def test_validate_no_future_leak_string_datetime_column() -> None:
    df = pd.DataFrame({"datetime": ["2024-01-01T00:00:00Z"]})
    assert validate_no_future_leak(df, cutoff_timestamp=1_700_000_000_000) is True  # 143->126


def test_detect_outliers_constant_series() -> None:
    df = pd.DataFrame({"close": [10.0, 10.0, 10.0]})
    assert not _detect_outliers(df, 5.0).any()  # std == 0 -> all False


# ===========================================================================
# feature_store.py
# ===========================================================================


class _RecordingComputer:
    def __init__(self) -> None:
        self.last_df: pd.DataFrame | None = None

    def compute_all(self, df: pd.DataFrame, indicator_names: list[str] | None = None):
        self.last_df = df.copy()
        out = df.copy()
        out["fake_ind"] = 1.0
        return out


class _NoTsComputer:
    def compute_meta_features(self, features: pd.DataFrame, funding: Any, oi: Any) -> pd.DataFrame:
        return pd.DataFrame({"meta_col": [1.0] * len(features)})


class _FakeMetaStore:
    def query_funding_rates(self, symbol: str, end: int | None = None) -> pd.DataFrame:
        return pd.DataFrame()

    def query_open_interest(self, symbol: str, end: int | None = None) -> pd.DataFrame:
        return pd.DataFrame()


class _FakeRaw:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def query(self, symbol: str, start: int | None = None, end: int | None = None) -> pd.DataFrame:
        return self.frame


def test_feature_store_append_meta_guards(tmp_path) -> None:
    fs = FeatureStore(str(tmp_path / "feat"), indicator_computer=_RecordingComputer())
    raw = _FakeRaw(pd.DataFrame({"timestamp": [500], "close": [1.0]}))
    features = pd.DataFrame({"timestamp": [500], "close": [1.0], "fake_ind": [1.0]})

    # Defensive guard: meta computer cleared -> unchanged features (102).
    fs._meta_computer = None
    out = fs._append_meta_features(features, "BTC/USDT", 500, _FakeMetaStore())
    assert out is features

    # Computer returns a frame without timestamp -> backfill (105).
    fs._meta_computer = _NoTsComputer()
    out2 = fs.compute_features("BTC/USDT", 500, [], raw_store=raw, meta_store=_FakeMetaStore())
    assert "timestamp" in out2.columns and out2["meta_col"].tolist() == [1.0]


def test_feature_store_read_feature_source_empty_dir(tmp_path) -> None:
    fs = FeatureStore(str(tmp_path / "feat"))
    (fs._parquet_dir / "BTC_USDT").mkdir(parents=True, exist_ok=True)
    assert fs.load_features("BTC/USDT").empty  # 220-221 empty dir -> None source

    # Direct static call with no filters (235).
    assert FeatureStore._candidate_paths(fs._parquet_dir / "BTC_USDT", None, None) == []
