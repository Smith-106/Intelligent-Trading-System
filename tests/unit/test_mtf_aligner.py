"""Tests for multi-timeframe data alignment."""

from __future__ import annotations

import logging
from typing import cast

import pandas as pd
import pytest

from quantflow.data.fetcher import DataFetcher
from quantflow.data.mtf_aligner import MTFAligner


def _make_frame(
    start: str,
    periods: int,
    freq: str,
    *,
    tz: str | None = None,
    with_timestamp: bool = True,
) -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq=freq, tz=tz)
    frame = pd.DataFrame(
        {
            "open": range(periods),
            "high": range(1, periods + 1),
            "low": range(periods),
            "close": range(periods),
            "volume": [100] * periods,
        },
        index=index,
    )
    if with_timestamp:
        frame["timestamp"] = (frame.index.view("int64") // 1_000_000).astype("int64")
    return frame


class _FakeFetcher:
    def __init__(self, mapping: dict[str, pd.DataFrame | Exception]):
        self.mapping = mapping
        self.calls: list[tuple[str, str, str | None, str | None]] = []

    def fetch_ohlcv(
        self,
        *,
        symbol: str,
        timeframe: str,
        start: str | None,
        end: str | None,
    ) -> pd.DataFrame:
        self.calls.append((symbol, timeframe, start, end))
        result = self.mapping[timeframe]
        if isinstance(result, Exception):
            raise result
        return result


def test_align_requires_at_least_three_timeframes() -> None:
    aligner = MTFAligner()

    with pytest.raises(ValueError, match="Need at least 3 timeframes"):
        aligner.align("BTC/USDT", timeframes=["1W", "4H"])


def test_fetch_timeframe_returns_none_without_fetcher() -> None:
    aligner = MTFAligner()

    assert aligner._fetch_timeframe("BTC/USDT", "1H", None, None) is None


def test_fetch_timeframe_maps_timeframe_and_logs_failures(caplog: pytest.LogCaptureFixture) -> None:
    fetcher = _FakeFetcher(
        {"7D": RuntimeError("boom"), "4h": _make_frame("2024-01-01", 2, "4h", tz="UTC")}
    )
    aligner = MTFAligner(fetcher=cast(DataFetcher, fetcher))

    ok = aligner._fetch_timeframe("BTC/USDT", "4H", "2024-01-01", "2024-01-10")
    with caplog.at_level(logging.WARNING):
        failed = aligner._fetch_timeframe("BTC/USDT", "1W", "2024-01-01", "2024-01-10")

    assert ok is not None
    assert failed is None
    assert fetcher.calls[0] == ("BTC/USDT", "4h", "2024-01-01", "2024-01-10")
    assert fetcher.calls[1] == ("BTC/USDT", "7D", "2024-01-01", "2024-01-10")
    assert "Failed to fetch BTC/USDT 1W data" in caplog.text


def test_create_aligned_index_handles_empty_inputs_and_localizes_primary() -> None:
    aligner = MTFAligner()
    primary = _make_frame("2024-01-01", 2, "1D", tz=None)

    empty_idx = aligner._create_aligned_index(pd.DataFrame(), pd.DataFrame())
    primary_idx = aligner._create_aligned_index(pd.DataFrame(), primary)

    assert empty_idx.empty
    assert str(empty_idx.tz) == "UTC"
    assert str(primary_idx.tz) == "UTC"


def test_create_aligned_index_prefers_minor_index_and_localizes_to_utc() -> None:
    aligner = MTFAligner()
    minor = _make_frame("2024-01-01", 3, "1h", tz=None)
    primary = _make_frame("2024-01-01", 2, "1D", tz="UTC")

    aligned = aligner._create_aligned_index(minor, primary)

    assert len(aligned) == 3
    assert str(aligned.tz) == "UTC"


def test_reindex_to_utc_returns_empty_or_forward_filled_frames() -> None:
    aligner = MTFAligner()
    aligned_index = pd.date_range("2024-01-01 05:00:00", periods=3, freq="1h", tz="UTC")

    assert aligner._reindex_to_utc(pd.DataFrame(), aligned_index).empty
    assert (
        aligner._reindex_to_utc(
            _make_frame("2024-01-01", 2, "1h", tz="UTC"), pd.DatetimeIndex([])
        ).shape[0]
        == 2
    )

    eastern = _make_frame("2024-01-01", 2, "1h", tz="US/Eastern")
    reindexed = aligner._reindex_to_utc(eastern, aligned_index)

    assert list(reindexed.index) == list(aligned_index)
    # Leak-safe semantics (P0.1): HTF bar values become visible only at bar
    # close. eastern bar A opens 00:00-05 (close=0), bar B opens 01:00-05
    # (close=1); after +1h shift they are visible at 01:00-05=06:00Z and
    # 02:00-05=07:00Z. aligned_index 05:00Z precedes the first closed bar
    # -> NaN; 06:00Z -> bar A close (0); 07:00Z -> bar B close (1).
    assert pd.isna(reindexed.loc[aligned_index[0], "close"])
    assert reindexed.loc[aligned_index[1], "close"] == 0
    assert reindexed.loc[aligned_index[2], "close"] == 1


def test_fallback_align_uses_available_frames_and_localizes_index() -> None:
    aligner = MTFAligner()
    weekly = _make_frame("2024-01-01", 2, "7D", tz=None)
    hourly = _make_frame("2024-01-01", 3, "1h", tz=None)

    aligned = aligner._fallback_align({"1W": weekly, "1H": hourly}, ["1W", "4H", "1H"])

    assert aligned.primary.equals(weekly)
    assert aligned.intermediate.equals(hourly)
    assert aligned.minor.empty
    assert str(aligned.aligned_index.tz) == "UTC"


def test_fallback_align_uses_minor_index_when_minor_frame_is_present() -> None:
    aligner = MTFAligner()
    weekly = _make_frame("2024-01-01", 2, "7D", tz="UTC")
    four_hour = _make_frame("2024-01-01", 3, "4h", tz="UTC")
    hourly = _make_frame("2024-01-01", 4, "1h", tz=None)

    aligned = aligner._fallback_align(
        {"1W": weekly, "4H": four_hour, "1H": hourly},
        ["1W", "4H", "1H"],
    )

    assert aligned.primary.equals(weekly)
    assert aligned.intermediate.equals(four_hour)
    assert aligned.minor.equals(hourly)
    assert str(aligned.aligned_index.tz) == "UTC"
    assert len(aligned.aligned_index) == len(hourly)


def test_align_reindexes_all_three_timeframes() -> None:
    weekly = _make_frame("2024-01-01", 2, "7D", tz=None)
    four_hour = _make_frame("2024-01-01", 4, "4h", tz="UTC")
    hourly = _make_frame("2024-01-01", 6, "1h", tz=None)
    fetcher = _FakeFetcher({"7D": weekly, "4h": four_hour, "1h": hourly})

    aligned = MTFAligner(fetcher=cast(DataFetcher, fetcher)).align(
        "BTC/USDT",
        timeframes=["1W", "4H", "1H"],
        start="2024-01-01",
        end="2024-01-31",
    )

    assert aligned.timeframes == ["1W", "4H", "1H"]
    assert len(aligned.aligned_index) == len(hourly)
    assert list(aligned.primary.index) == list(aligned.aligned_index)
    assert list(aligned.intermediate.index) == list(aligned.aligned_index)
    assert list(aligned.minor.index) == list(aligned.aligned_index)


def test_align_falls_back_when_fewer_than_three_frames_available() -> None:
    weekly = _make_frame("2024-01-01", 2, "7D", tz="UTC")
    hourly = _make_frame("2024-01-01", 6, "1h", tz="UTC")
    fetcher = _FakeFetcher({"7D": weekly, "4h": pd.DataFrame(), "1h": hourly})

    aligned = MTFAligner(fetcher=cast(DataFetcher, fetcher)).align(
        "BTC/USDT", timeframes=["1W", "4H", "1H"]
    )

    assert aligned.primary.equals(weekly)
    assert aligned.intermediate.equals(hourly)
    assert aligned.minor.empty


# ---------------------------------------------------------------------------
# P0.0 — Multi-timeframe look-ahead verification (deep-research F1)
#
# CCXT fetch_ohlcv timestamps are bar-OPEN (fetcher.py:102-105). A higher-
# timeframe (HTF) bar's OHLCV — especially `close` — is only known AFTER the
# bar closes (open_ts + timeframe). `_reindex_to_utc` (:177) does
# `reindex(aligned_index).ffill()`. If the aligned index contains a minor
# timestamp that falls strictly INSIDE an HTF bar (i.e. open_ts < minor_ts <
# close_ts), reindex maps the HTF bar's own open_ts onto itself and ffill
# propagates the *unclosed* HTF bar's close forward to subsequent minor bars
# — a look-ahead leak.
#
# Leak-safe behaviour: a minor bar at time T may only see an HTF bar whose
# close_ts <= T (i.e. the most recent FULLY CLOSED HTF bar).
# ---------------------------------------------------------------------------


def test_mtf_does_not_expose_unclosed_htf_bar_close_to_minor() -> None:
    """P0.0: assert no unclosed-HTF-value leakage across the HTF boundary.

    CCXT timestamps are bar-OPEN (fetcher.py:102-105), so an HTF bar's
    `close` is only known at open_ts + timeframe. `_reindex_to_utc` (:177)
    does `reindex(aligned_index).ffill()`. If the aligned (minor) index
    contains a timestamp that falls strictly INSIDE an HTF bar (open_ts <=
    minor_ts < close_ts), the HTF bar's open_ts aligns to itself and ffill
    propagates the *unclosed* HTF close to subsequent minor bars — a
    look-ahead leak. Leak-safe: a minor bar at T may only see an HTF bar
    whose close_ts <= T (most recent FULLY CLOSED HTF bar).

    Tests the intermediate (1H) frame against minor (15m); primary=1W is a
    coarse anchor so intermediate is the leak-bearing HTF here.
    """
    # intermediate: two 1H bars. Bar A opens 09:00 (close=1, closes 10:00);
    # bar B opens 10:00 (close=2, closes 11:00). bar-open timestamps.
    intermediate = _make_frame("2024-01-01 09:00", 2, "1h", tz="UTC")
    # minor: 15m bars 09:00..10:45 (8 bars). 10:00/10:15/10:30/10:45 fall
    # INSIDE the unclosed 1H bar B (opens 10:00, closes 11:00).
    minor = _make_frame("2024-01-01 09:00", 8, "15min", tz="UTC")
    primary = _make_frame("2024-01-01", 2, "7D", tz="UTC")
    fetcher = _FakeFetcher({"7D": primary, "4h": intermediate, "15min": minor})
    # timeframes: primary=1W, intermediate=4H(mapped->4h fetch), minor=15m.
    aligned = MTFAligner(fetcher=cast(DataFetcher, fetcher)).align(
        "BTC/USDT", timeframes=["1W", "4H", "15m"]
    )

    bar_b_open = pd.Timestamp("2024-01-01 10:00", tz="UTC")
    bar_b_close = pd.Timestamp("2024-01-01 11:00", tz="UTC")
    inside_b = [t for t in aligned.intermediate.index if bar_b_open <= t < bar_b_close]

    # Bar A's close (last fully-closed 1H bar before bar B) == 1.
    bar_a_close = intermediate.iloc[0]["close"]

    for t in inside_b:
        seen_close = aligned.intermediate.loc[t, "close"]
        assert seen_close == bar_a_close, (
            f"LOOK-AHEAD LEAK at minor ts={t}: saw HTF close={seen_close} "
            f"(unclosed bar B close={intermediate.iloc[1]['close']}) "
            f"instead of last-closed bar A close={bar_a_close}"
        )
