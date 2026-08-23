"""Unit tests for the multi-timeframe resampling layer (PERF-REV015)."""

from __future__ import annotations

import pandas as pd
import pytest

from quantflow.data.resample import (
    ANALYSIS_TIMEFRAMES,
    BASE_TIMEFRAMES,
    base_timeframe_for,
    resample_ohlcv,
    timeframe_to_ms,
    timeframe_to_timedelta,
)


def _base_5m(n: int = 300, start_ms: int | None = None) -> pd.DataFrame:
    if start_ms is None:
        # aligned to a true grid edge covering every tested derived period
        # (45m is the largest; aligning to it also lands on 15m/30m edges)
        start_ms = (1_700_000_000_000 // 900_000) * 900_000
    ts = [start_ms + i * 300_000 for i in range(n)]
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": [100.0 + i * 0.1 for i in range(n)],
            "high": [101.0 + i * 0.1 for i in range(n)],
            "low": [99.0 + i * 0.1 for i in range(n)],
            "close": [100.5 + i * 0.1 for i in range(n)],
            "volume": [10.0] * n,
            "symbol": ["BTC/USDT"] * n,
            "timeframe": ["5m"] * n,
            "datetime": pd.to_datetime(ts, unit="ms", utc=True),
        }
    )


class TestTimeframeParsing:
    def test_all_analysis_timeframes_parse(self) -> None:
        assert len(ANALYSIS_TIMEFRAMES) == 24
        for tf in ANALYSIS_TIMEFRAMES:
            assert timeframe_to_ms(tf) > 0
            assert timeframe_to_timedelta(tf) == pd.Timedelta(timeframe_to_ms(tf), unit="ms")

    @pytest.mark.parametrize("bad", ["0m", "-5m", "5x", "", "45"])
    def test_invalid_timeframes_raise(self, bad: str) -> None:
        with pytest.raises(ValueError):
            timeframe_to_ms(bad)

    def test_base_partition_covers_every_analysis_tf(self) -> None:
        # every analysis bucket derives from exactly one base grid
        derived = {tf: base_timeframe_for(tf) for tf in ANALYSIS_TIMEFRAMES}
        assert set(derived.values()) == set(BASE_TIMEFRAMES)
        # spot-check the documented mapping (4h derives from the 5m grid)
        assert derived["4h"] == "5m"
        assert derived["45m"] == "5m"
        assert derived["32h"] == "5m"
        assert derived["24h"] == "1d"
        assert derived["30d"] == "1d"

    def test_non_multiple_raises(self) -> None:
        # 47m is not a multiple of 5m — would produce lossy buckets
        with pytest.raises(ValueError):
            base_timeframe_for("47m")


class TestResampleOhlcv:
    def test_bucket_mapping_contract(self) -> None:
        base = _base_5m(12)  # one full hour of 5m bars
        out = resample_ohlcv(base, "15m")
        assert len(out) == 4
        first = out.iloc[0]
        assert first["open"] == pytest.approx(base["open"].iloc[0])
        assert first["high"] == pytest.approx(base["high"][:3].max())
        assert first["low"] == pytest.approx(base["low"][:3].min())
        assert first["close"] == pytest.approx(base["close"].iloc[2])
        assert first["volume"] == pytest.approx(30.0)
        # timestamp is the bucket's left edge
        assert int(first["timestamp"]) == int(base["timestamp"].iloc[0])

    def test_idempotent(self) -> None:
        base = _base_5m(500)
        once = resample_ohlcv(base, "45m")
        twice = resample_ohlcv(base, "45m")
        pd.testing.assert_frame_equal(once, twice)

    def test_leak_safe_trailing_partial_bucket_dropped(self) -> None:
        # 7 bars = one full 30m bucket + one bar that cannot complete it
        base = _base_5m(7)
        out = resample_ohlcv(base, "30m")
        assert len(out) == 1
        assert int(out["timestamp"].iloc[0]) == int(base["timestamp"].iloc[0])

    def test_sparse_buckets_survive_gaps(self) -> None:
        base = _base_5m(12)
        dropped = base.drop(index=[3, 4]).reset_index(drop=True)
        out = resample_ohlcv(dropped, "15m")
        # middle 15m bucket has only one sub-bar but still aggregates
        assert len(out) >= 3

    def test_single_base_bar_degrades_to_empty(self) -> None:
        # REV-017-RV3: one 5m bar cannot complete any larger bucket — it must
        # NOT be presented as a full candle (old fallback used the analysis
        # period as base_period and let the partial bucket through).
        base = _base_5m(1)
        out = resample_ohlcv(base, "30m")
        assert out.empty

    def test_empty_input_returns_empty(self) -> None:
        base = _base_5m(10).iloc[0:0]
        out = resample_ohlcv(base, "1h")
        assert out.empty
