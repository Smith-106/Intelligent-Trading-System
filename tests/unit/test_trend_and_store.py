"""Tests for trend helpers and DataStore utility branches."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantflow.data.store import DataStore, _validate_columns, _validate_symbol
from quantflow.indicators import trend


def _make_ohlcv_frame() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=4, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": [int(d.timestamp() * 1000) for d in dates],
            "datetime": dates,
            "open": [100.0, 101.0, 102.0, 103.0],
            "high": [101.0, 102.0, 103.0, 104.0],
            "low": [99.0, 100.0, 101.0, 102.0],
            "close": [100.5, 101.5, 102.5, 103.5],
            "volume": [10.0, 11.0, 12.0, 13.0],
            "timeframe": ["1d"] * 4,
        }
    )


class TestTrendFunctions:
    def test_sma_ema_and_dema(self):
        series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])

        sma = trend.sma(series, period=3)
        ema = trend.ema(series, period=3)
        dema = trend.dema(series, period=3)

        assert np.isnan(sma.iloc[1])
        assert sma.iloc[2] == pytest.approx(2.0)
        assert ema.iloc[-1] > ema.iloc[0]
        assert dema.iloc[-1] > ema.iloc[-1]

    def test_macd_returns_expected_columns(self):
        series = pd.Series(np.linspace(100, 120, 20))

        result = trend.macd(series, fast=3, slow=6, signal=2)

        assert list(result.columns) == ["macd", "macd_signal", "macd_histogram"]
        assert len(result) == len(series)

    def test_supertrend_and_adx_cover_direction_paths(self):
        high = pd.Series([10, 11, 12, 13, 12, 11, 10], dtype=float)
        low = pd.Series([9, 10, 11, 12, 11, 10, 9], dtype=float)
        close = pd.Series([9.5, 10.5, 11.5, 12.5, 11.0, 10.0, 9.5], dtype=float)

        supertrend = trend.supertrend(high, low, close, period=2, multiplier=1.0)
        adx = trend.adx(high, low, close, period=2)

        assert "supertrend" in supertrend.columns
        assert "supertrend_direction" in supertrend.columns
        assert set(supertrend["supertrend_direction"].dropna().astype(int).unique()).issubset(
            {-1, 1}
        )
        assert len(adx) == len(close)
        assert adx.dropna().ge(0).all()

    def test_supertrend_hits_explicit_up_and_down_direction_branches(self):
        high = pd.Series([10.0, 10.0, 10.0], dtype=float)
        low = pd.Series([9.0, 9.0, 9.0], dtype=float)
        close = pd.Series([9.5, 11.0, 8.0], dtype=float)

        result = trend.supertrend(high, low, close, period=1, multiplier=1.0)

        assert result["supertrend_direction"].tolist() == [1, 1, -1]
        assert result["supertrend"].iloc[1] == pytest.approx(8.5)
        assert result["supertrend"].iloc[2] == pytest.approx(8.5)


class TestDataStoreHelpers:
    def test_validate_symbol_accepts_and_rejects_values(self):
        assert _validate_symbol("BTC/USDT") == "BTC_USDT"

        with pytest.raises(ValueError, match="Invalid symbol format"):
            _validate_symbol("BTC;DROP TABLE")

    @pytest.mark.parametrize(
        "symbol,why",
        [
            ("BTC'USDT", "single quote — breaks out of DuckDB glob literal (SQLi)"),
            ('BTC"USDT', "double quote — SQL identifier breakout"),
            ("BTC\\USDT", "backslash — Windows path separator (traversal)"),
            ("../etc/passwd", "dot-slash — path traversal"),
            ("..\\etc", "dot-backslash — Windows path traversal"),
            ("BTC*USDT", "asterisk — glob metachar (read unintended files)"),
            ("BTC[USDT", "bracket — glob character class"),
            ("BTC USDT", "space — breaks glob literal parsing"),
            ("BTC|USDT", "pipe — shell metachar"),
            ("BTC`USDT", "backtick — shell metachar"),
            ("BTC$USDT", "dollar — shell/SQL interpolation"),
            ("BTC.USDT", "dot — could masquerade as file extension / relative path"),
            ("A" * 21, "over 20 chars — bound the input length"),
            ("", "empty — no symbol"),
        ],
    )
    def test_validate_symbol_rejects_security_relevant_chars(self, symbol, why):
        """SYMBOL_PATTERN must reject every character that could break out of
        a DuckDB glob literal, traverse the parquet dir, or inject SQL/shell
        metachars. This is the explicit security closure for the SEC-001 /
        REV-005 / REV-008 fix — the validators are exercised indirectly via
        save/query, but a focused rejection test makes the contract explicit
        (an adversarial reviewer flagged this gap as non-blocking)."""
        with pytest.raises(ValueError, match="Invalid symbol format"):
            _validate_symbol(symbol)

    def test_validate_columns_deduplicates_and_rejects_invalid_values(self):
        assert _validate_columns(["timestamp", "close", "close"]) == ["timestamp", "close"]

        with pytest.raises(ValueError, match="columns must not be empty"):
            _validate_columns([])

        with pytest.raises(ValueError, match="Invalid column name"):
            _validate_columns(["timestamp", "close;DROP TABLE"])

    def test_save_requires_datetime_or_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(str(Path(tmp) / "pq"))
            with pytest.raises(ValueError, match="must have 'datetime' or 'timestamp'"):
                store.save(pd.DataFrame({"close": [1.0]}), "BTC/USDT")
            store.close()

    def test_save_ignores_empty_frames_and_merges_existing_partition(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(str(Path(tmp) / "pq"), str(Path(tmp) / "db.duckdb"))
            store.save(pd.DataFrame(), "BTC/USDT")

            first = _make_ohlcv_frame().iloc[:2].copy()
            second = _make_ohlcv_frame().iloc[1:4].copy()
            second.loc[:, "close"] = [201.0, 202.0, 203.0]
            second.loc[:, "data_source"] = ["okx", "okx", "okx"]

            store.save(first, "BTC/USDT")
            store.save(second, "BTC/USDT")
            merged = store.query("BTC/USDT")
            projected = store.query("BTC/USDT", columns=["timestamp", "close", "data_source"])

            assert list(merged["timestamp"]) == sorted(
                set(first["timestamp"]) | set(second["timestamp"])
            )
            assert len(merged) == 4
            assert "data_source" in merged.columns
            assert projected["close"].tolist() == [100.5, 201.0, 202.0, 203.0]
            # Pandas/parquet converts None to NaN in string columns
            projected_data = projected["data_source"].tolist()
            # First element may be None or NaN depending on parquet backend
            assert projected_data[1:] == ["okx", "okx", "okx"]
            assert pd.isna(projected_data[0]) or projected_data[0] is None
            store.close()

    def test_query_filters_and_get_date_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(str(Path(tmp) / "pq"), str(Path(tmp) / "db.duckdb"))
            frame = _make_ohlcv_frame()
            store.save(frame, "BTC/USDT")

            result = store.query(
                "BTC/USDT",
                start=frame["timestamp"].iloc[1],
                end=frame["timestamp"].iloc[2],
                timeframe="1d",
            )
            date_range = store.get_date_range("BTC/USDT")

            assert list(result["timestamp"]) == [
                frame["timestamp"].iloc[1],
                frame["timestamp"].iloc[2],
            ]
            assert date_range == (frame["timestamp"].min(), frame["timestamp"].max())
            store.close()

    def test_query_projects_columns_and_prunes_month_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(str(Path(tmp) / "pq"), str(Path(tmp) / "db.duckdb"))
            dates = pd.to_datetime(
                ["2024-01-30", "2024-01-31", "2024-02-01", "2024-02-02"],
                utc=True,
            )
            frame = pd.DataFrame(
                {
                    "timestamp": [int(d.timestamp() * 1000) for d in dates],
                    "datetime": dates,
                    "open": [100.0, 101.0, 102.0, 103.0],
                    "high": [101.0, 102.0, 103.0, 104.0],
                    "low": [99.0, 100.0, 101.0, 102.0],
                    "close": [100.5, 101.5, 102.5, 103.5],
                    "volume": [10.0, 11.0, 12.0, 13.0],
                    "timeframe": ["1d"] * 4,
                }
            )
            store.save(frame, "BTC/USDT")

            jan_paths = store._candidate_paths(
                Path(tmp) / "pq" / "BTC_USDT",
                int(frame["timestamp"].iloc[0]),
                int(frame["timestamp"].iloc[1]),
            )
            result = store.query(
                "BTC/USDT",
                start=frame["timestamp"].iloc[0],
                end=frame["timestamp"].iloc[1],
                columns=("timestamp", "close"),
            )

            assert [path.name for path in jan_paths] == ["01.parquet"]
            assert list(result.columns) == ["timestamp", "close"]
            assert result["timestamp"].tolist() == frame["timestamp"].iloc[:2].tolist()
            store.close()

    def test_get_date_range_handles_missing_symbol_and_existing_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(str(Path(tmp) / "pq"), str(Path(tmp) / "db.duckdb"))
            frame = _make_ohlcv_frame()
            store.save(frame, "BTC/USDT")
            parquet_file = Path(tmp) / "pq" / "BTC_USDT" / "2024" / "01.parquet"

            existing = store._load_existing(parquet_file)
            missing = store._load_existing(Path(tmp) / "pq" / "missing.parquet")
            grouped = DataStore.group_cols(
                pd.DataFrame(columns=["timestamp", "year", "month", "close"])
            )

            assert existing is not None and not existing.empty
            assert missing is None
            assert grouped == ["timestamp", "close"]
            assert store.get_date_range("ETH/USDT") is None
            store.close()

    def test_save_append_only_fast_path_skips_resort_on_non_overlapping_append(self):
        # ISS-034: when appended bars are all newer than the stored max, save
        # skips drop_duplicates + sort_values + reset_index on the full month
        # (both sides already sorted, no overlap). Assert the fast path still
        # produces a correctly-ordered, dedup-free partition identical to the
        # slow path's output.
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(str(Path(tmp) / "pq"), str(Path(tmp) / "db.duckdb"))
            base = _make_ohlcv_frame()  # 4 daily bars 2024-01-01..04
            store.save(base, "BTC/USDT")

            # Append 2 NEW bars strictly newer than the stored max (Jan 5, 6).
            new_dates = pd.date_range("2024-01-05", periods=2, freq="D", tz="UTC")
            append = pd.DataFrame(
                {
                    "timestamp": [int(d.timestamp() * 1000) for d in new_dates],
                    "datetime": new_dates,
                    "open": [104.0, 105.0],
                    "high": [105.0, 106.0],
                    "low": [103.0, 104.0],
                    "close": [104.5, 105.5],
                    "volume": [14.0, 15.0],
                    "timeframe": ["1d", "1d"],
                }
            )
            store.save(append, "BTC/USDT")
            merged = store.query("BTC/USDT", columns=["timestamp", "close"])

            assert len(merged) == 6
            # Strictly ascending — fast-path concat preserved order.
            ts = merged["timestamp"].tolist()
            assert ts == sorted(ts)
            assert ts == list(base["timestamp"]) + list(append["timestamp"])
            assert merged["close"].tolist() == [100.5, 101.5, 102.5, 103.5, 104.5, 105.5]
            store.close()


    def test_save_keeps_multiple_timeframes_at_same_timestamp(self):
        # Multi-TF co-residence: 1h and 1d can share a wall-clock open time.
        # Dedup must key on (timestamp, timeframe), not timestamp alone.
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(str(Path(tmp) / "pq"), str(Path(tmp) / "db.duckdb"))
            base = _make_ohlcv_frame()  # 1d bars
            store.save(base, "BTC/USDT")

            # Same timestamps as base, different timeframe label.
            hourly = base.copy()
            hourly.loc[:, "timeframe"] = "1h"
            hourly.loc[:, "close"] = [200.5, 201.5, 202.5, 203.5]
            store.save(hourly, "BTC/USDT")

            all_rows = store.query("BTC/USDT")
            assert len(all_rows) == 8
            assert sorted(all_rows["timeframe"].unique().tolist()) == ["1d", "1h"]
            d1 = store.query("BTC/USDT", timeframe="1d")
            h1 = store.query("BTC/USDT", timeframe="1h")
            assert len(d1) == 4
            assert len(h1) == 4
            assert d1["close"].tolist() == [100.5, 101.5, 102.5, 103.5]
            assert h1["close"].tolist() == [200.5, 201.5, 202.5, 203.5]
            store.close()

    def test_save_falls_back_to_full_merge_on_overlapping_timestamps(self):
        # ISS-034: overlapping append (re-saving an existing bar) must still
        # run drop_duplicates(keep="last") so the newer row wins — the fast
        # path is skipped because new_min <= existing_max.
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(str(Path(tmp) / "pq"), str(Path(tmp) / "db.duckdb"))
            base = _make_ohlcv_frame()
            store.save(base, "BTC/USDT")

            # Re-save bars 2..4 with updated closes (overlap on Jan 2,3,4).
            overlap = base.iloc[1:4].copy()
            overlap.loc[:, "close"] = [999.0, 998.0, 997.0]
            store.save(overlap, "BTC/USDT")
            merged = store.query("BTC/USDT", columns=["timestamp", "close"])

            assert len(merged) == 4  # no duplicate rows
            # keep="last": updated closes win for the overlapped bars.
            assert merged["close"].tolist() == [100.5, 999.0, 998.0, 997.0]
            store.close()
