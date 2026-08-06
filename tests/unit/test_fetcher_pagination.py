"""Tests for DataFetcher OHLCV pagination (multi-page fetch)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pandas as pd

from quantflow.data.fetcher import (
    MAX_PAGINATION_PAGES,
    OKX_KLINE_PAGE_MAX,
    DataFetcher,
)


def _page(start_ts: int, n: int, step_ms: int = 3_600_000) -> list[list[float]]:
    """Synthetic CCXT bar page starting at start_ts (ms)."""
    return [
        [start_ts + i * step_ms, 100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i, 10.0 + i]
        for i in range(n)
    ]


def _make_fetcher(pages: list[list[list[float]]]) -> tuple[DataFetcher, AsyncMock]:
    """Fetcher whose exchange returns the given page sequence."""
    fetcher = DataFetcher.__new__(DataFetcher)
    exchange = MagicMock()
    exchange.parse8601.side_effect = lambda s: int(
        pd.Timestamp(s).timestamp() * 1000
    )
    mock_call = AsyncMock(side_effect=pages)
    exchange.fetch_ohlcv = mock_call
    fetcher._exchange = exchange
    return fetcher, mock_call


class TestPagination:
    def test_multi_page_with_end_covers_full_window(self) -> None:
        """3 pages x 300 bars with a wide end window -> all bars merged."""
        p1 = _page(1_700_000_000_000, 300)
        p2 = _page(1_700_000_000_000 + 300 * 3_600_000, 300)
        p3 = _page(1_700_000_000_000 + 600 * 3_600_000, 300)
        fetcher, mock_call = _make_fetcher([p1, p2, p3, []])
        # 900 bars from 2023-11-14 → ~2023-12-21; end 2024-01-01 covers all,
        # so the loop keeps paginating until the empty page terminates it.
        df = asyncio.run(fetcher.fetch_ohlcv("BTC/USDT", "1h", start="2023-11-01", end="2024-01-01"))
        assert len(df) == 900
        assert df["timestamp"].is_monotonic_increasing
        assert df["timestamp"].nunique() == 900  # no duplicates
        assert mock_call.call_count == 4

    def test_end_window_truncates_partial_last_page(self) -> None:
        """Bars past the end window are trimmed."""
        p1 = _page(1_700_000_000_000, 300)
        p2 = _page(1_700_000_000_000 + 300 * 3_600_000, 300)
        fetcher, _ = _make_fetcher([p1, p2])
        # end = 2023-12-01 → end_ts = 1701388799000; p2 exceeds it partially.
        df = asyncio.run(fetcher.fetch_ohlcv("BTC/USDT", "1h", start="2023-11-01", end="2023-11-15"))
        end_ts = int(pd.Timestamp("2023-11-15T23:59:59Z").timestamp() * 1000)
        assert df["timestamp"].max() <= end_ts
        assert len(df) < 600

    def test_short_page_without_end_stops_after_one_page(self) -> None:
        """No end and a short page (< page cap) → single page, no extra fetch."""
        p1 = _page(1_700_000_000_000, 100)
        fetcher, mock_call = _make_fetcher([p1])
        df = asyncio.run(fetcher.fetch_ohlcv("BTC/USDT", "1h"))
        assert len(df) == 100
        assert mock_call.call_count == 1

    def test_full_pages_without_end_keeps_paginating(self) -> None:
        """No end but full pages → keeps fetching until short/empty page."""
        p1 = _page(1_700_000_000_000, OKX_KLINE_PAGE_MAX)
        p2 = _page(1_700_000_000_000 + OKX_KLINE_PAGE_MAX * 3_600_000, 50)
        fetcher, mock_call = _make_fetcher([p1, p2])
        df = asyncio.run(fetcher.fetch_ohlcv("BTC/USDT", "1h"))
        assert len(df) == 350
        assert mock_call.call_count == 2

    def test_empty_first_page_returns_empty(self) -> None:
        fetcher, mock_call = _make_fetcher([[]])
        df = asyncio.run(fetcher.fetch_ohlcv("BTC/USDT", "1h"))
        assert df.empty
        assert mock_call.call_count == 1

    def test_page_cap_protects_against_hang(self) -> None:
        """Runaway pagination stops at MAX_PAGINATION_PAGES."""
        pages = [_page(1_700_000_000_000 + i * OKX_KLINE_PAGE_MAX * 3_600_000, OKX_KLINE_PAGE_MAX) for i in range(600)]
        fetcher, mock_call = _make_fetcher(pages)
        df = asyncio.run(fetcher.fetch_ohlcv("BTC/USDT", "1h"))
        assert mock_call.call_count == MAX_PAGINATION_PAGES
        assert len(df) == MAX_PAGINATION_PAGES * OKX_KLINE_PAGE_MAX

    def test_non_finite_bars_filtered(self) -> None:
        """Non-finite bars are dropped at the parse boundary."""
        p1 = _page(1_700_000_000_000, 50)
        p1.append([1_700_000_000_000 + 50 * 3_600_000, float("nan"), 1.0, 1.0, 1.0, 1.0])
        fetcher, _ = _make_fetcher([p1])
        df = asyncio.run(fetcher.fetch_ohlcv("BTC/USDT", "1h"))
        assert len(df) == 50
