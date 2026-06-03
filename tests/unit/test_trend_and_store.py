"""Tests for trend helpers and DataStore utility branches."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantflow.data.store import DataStore, _validate_symbol
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

            store.save(first, "BTC/USDT")
            store.save(second, "BTC/USDT")
            merged = store.query("BTC/USDT")

            assert list(merged["timestamp"]) == sorted(
                set(first["timestamp"]) | set(second["timestamp"])
            )
            assert len(merged) == 4
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
