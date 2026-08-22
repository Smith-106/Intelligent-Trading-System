"""Coverage closure tests for CCXT fetchers using local exchange doubles."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

import pandas as pd
import pytest

import quantflow.data.fetcher as fetcher_module
import quantflow.data.market_meta_fetcher as meta_module
from quantflow.common.config import DataConfig
from quantflow.common.exceptions import GatewayConnectionError
from quantflow.common.netretry import is_retryable_error as _is_retryable
from quantflow.common.netretry import to_float as _to_float
from quantflow.common.netretry import to_int as _to_int
from quantflow.data.fetcher import DataFetcher, _bar_is_finite
from quantflow.data.market_meta_fetcher import (
    MarketMetaFetcher,
    OpenInterestSnapshot,
    RateLimiter,
    is_oi_fresh,
)


def _fetcher(exchange: Any | None = None) -> DataFetcher:
    fetcher = DataFetcher(DataConfig())
    fetcher._exchange = exchange
    return fetcher


class _TradesExchange:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)

    async def fetch_trades(self, symbol: str, **kwargs: Any) -> Any:
        return self._responses.pop(0)


def test_bar_finiteness_rejects_short_none_and_uncoercible_values() -> None:
    assert not _bar_is_finite([1, 2])
    assert not _bar_is_finite([1, 1, 2, None, 2, 3])
    assert not _bar_is_finite([1, 1, 2, 0, "not-a-number", 3])
    assert _bar_is_finite([1, "1", 2, 0, 2, 3])


@pytest.mark.asyncio
async def test_fetcher_trade_and_nonfinite_ohlcv_boundaries() -> None:
    disconnected = _fetcher()
    with pytest.raises(GatewayConnectionError):
        await disconnected.fetch_trades("BTC/USDT")

    exchange = _TradesExchange(
        [
            [],
            ["not-a-trade"],
            [{"timestamp": 10, "price": "2.5", "amount": "3", "side": "buy"}],
        ]
    )
    fetcher = _fetcher(exchange)
    assert (await fetcher.fetch_trades("BTC/USDT")).empty
    assert (await fetcher.fetch_trades("BTC/USDT")).empty
    trades = await fetcher.fetch_trades("BTC/USDT", since=1, limit=7)
    assert trades.to_dict("records") == [
        {"timestamp": 10, "price": 2.5, "amount": 3.0, "side": "buy"}
    ]

    class _OhlcvExchange:
        def parse8601(self, value: str) -> int:
            return 0

        async def fetch_ohlcv(self, *args: Any, **kwargs: Any) -> list[list[Any]]:
            return [[1, 1.0, 2.0, 0.0, float("nan"), 10.0]]

    empty = await _fetcher(_OhlcvExchange()).fetch_ohlcv("BTC/USDT", timeframe="1h")
    assert empty.empty


@pytest.mark.asyncio
async def test_watch_trades_start_and_not_connected_paths() -> None:
    with pytest.raises(GatewayConnectionError):
        await _fetcher().watch_trades("BTC/USDT")

    class _BlockingExchange:
        async def watch_trades(self, symbol: str) -> list[dict[str, Any]]:
            await asyncio.Event().wait()
            return []

    fetcher = _fetcher(_BlockingExchange())
    await fetcher.watch_trades("BTC/USDT")
    task = fetcher._ws_task
    assert task is not None and fetcher._ws_running
    fetcher.stop_stream()
    with suppress(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_watch_trades_loop_covers_callback_fallback_and_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(fetcher_module.asyncio, "sleep", no_sleep)

    none_exchange = _fetcher()
    await none_exchange._watch_trades_loop("BTC/USDT", None, limit=1, poll_fallback_interval_s=0)

    class _AsyncWs:
        def __init__(self, owner: DataFetcher) -> None:
            self.owner = owner

        async def watch_trades(self, symbol: str) -> list[dict[str, Any]]:
            self.owner._ws_running = False
            return [{"timestamp": 1, "price": 2, "amount": 3, "side": "buy"}]

    async_fetcher = _fetcher()
    async_fetcher._exchange = _AsyncWs(async_fetcher)
    async_fetcher._ws_running = True
    async_seen: list[pd.DataFrame] = []

    async def async_callback(frame: pd.DataFrame) -> None:
        async_seen.append(frame)

    await async_fetcher._watch_trades_loop(
        "BTC/USDT", async_callback, limit=1, poll_fallback_interval_s=0
    )
    assert len(async_seen) == 1

    class _SyncWs:
        def __init__(self, owner: DataFetcher) -> None:
            self.owner = owner

        async def watch_trades(self, symbol: str) -> dict[str, Any]:
            self.owner._ws_running = False
            return {"timestamp": 2, "price": 4, "amount": 5, "side": "sell"}

    sync_fetcher = _fetcher()
    sync_fetcher._exchange = _SyncWs(sync_fetcher)
    sync_fetcher._ws_running = True
    sync_seen: list[pd.DataFrame] = []
    await sync_fetcher._watch_trades_loop(
        "BTC/USDT", lambda frame: sync_seen.append(frame), limit=1, poll_fallback_interval_s=0
    )
    assert sync_seen[0]["side"].tolist() == ["sell"]

    class _Fallback:
        def __init__(self, owner: DataFetcher) -> None:
            self.owner = owner

        async def fetch_trades(self, symbol: str, **kwargs: Any) -> list[Any]:
            self.owner._ws_running = False
            return []

    fallback_fetcher = _fetcher()
    fallback_fetcher._exchange = _Fallback(fallback_fetcher)
    fallback_fetcher._ws_running = True
    await fallback_fetcher._watch_trades_loop("BTC/USDT", None, limit=1, poll_fallback_interval_s=0)

    class _NoRowsWs:
        def __init__(self, owner: DataFetcher) -> None:
            self.owner = owner

        async def watch_trades(self, symbol: str) -> list[Any]:
            self.owner._ws_running = False
            return [object()]

    no_rows_fetcher = _fetcher()
    no_rows_fetcher._exchange = _NoRowsWs(no_rows_fetcher)
    no_rows_fetcher._ws_running = True
    await no_rows_fetcher._watch_trades_loop("BTC/USDT", None, limit=1, poll_fallback_interval_s=0)

    class _BrokenWs:
        async def watch_trades(self, symbol: str) -> list[Any]:
            raise RuntimeError("offline")

    broken_fetcher = _fetcher(_BrokenWs())
    broken_fetcher._ws_running = True

    async def stop_after_retry(_: float) -> None:
        broken_fetcher._ws_running = False

    monkeypatch.setattr(fetcher_module.asyncio, "sleep", stop_after_retry)
    await broken_fetcher._watch_trades_loop("BTC/USDT", None, limit=1, poll_fallback_interval_s=0)


@pytest.mark.asyncio
async def test_watch_trades_loop_reraises_cancellation_and_disconnect_noop() -> None:
    class _CancelledWs:
        async def watch_trades(self, symbol: str) -> list[Any]:
            raise asyncio.CancelledError()

    fetcher = _fetcher(_CancelledWs())
    fetcher._ws_running = True
    with pytest.raises(asyncio.CancelledError):
        await fetcher._watch_trades_loop("BTC/USDT", None, limit=1, poll_fallback_interval_s=0)
    assert not fetcher._ws_running

    await _fetcher().disconnect()


@pytest.mark.asyncio
async def test_stream_helpers_cover_empty_invalid_and_optional_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(fetcher_module.asyncio, "sleep", no_sleep)

    class _WsBars:
        def __init__(self, owner: DataFetcher) -> None:
            self.owner = owner
            self.calls = 0

        async def watch_ohlcv(self, symbol: str, timeframe: str) -> list[list[Any]]:
            self.calls += 1
            if self.calls == 1:
                return [[1, 1, 2, 0, None, 3]]
            self.owner._ws_running = False
            return [[2, 1, 2, 0, 1, 3]]

    ws_fetcher = _fetcher()
    ws_fetcher._exchange = _WsBars(ws_fetcher)
    ws_fetcher._ws_running = True
    await ws_fetcher._stream_ws("BTC/USDT", "1m", None)

    class _PollBars:
        def __init__(self, owner: DataFetcher) -> None:
            self.owner = owner
            self.calls = 0

        async def fetch_ohlcv(self, *args: Any, **kwargs: Any) -> list[list[Any]]:
            self.calls += 1
            if self.calls == 1:
                return [[1, 1, 2, 0, None, 3]]
            self.owner._ws_running = False
            return []

    poll_fetcher = _fetcher()
    poll_fetcher._exchange = _PollBars(poll_fetcher)
    poll_fetcher._ws_running = True
    await poll_fetcher._stream_poll("BTC/USDT", "1m", None, 0)

    class _OnePollBar:
        def __init__(self, owner: DataFetcher) -> None:
            self.owner = owner

        async def fetch_ohlcv(self, *args: Any, **kwargs: Any) -> list[list[Any]]:
            self.owner._ws_running = False
            return [[3, 1, 2, 0, 1, 3]]

    optional_callback = _fetcher()
    optional_callback._exchange = _OnePollBar(optional_callback)
    optional_callback._ws_running = True
    await optional_callback._stream_poll("BTC/USDT", "1m", None, 0)


@pytest.mark.asyncio
async def test_raw_watch_ohlcv_api_and_loop_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    await _fetcher().watch_ohlcv("BTC/USDT", "1m", lambda _: None)
    await _fetcher(object()).watch_ohlcv("BTC/USDT", "1m", lambda _: None)

    class _BlockingBars:
        async def watch_ohlcv(self, symbol: str, timeframe: str) -> list[list[Any]]:
            await asyncio.Event().wait()
            return []

    started = _fetcher(_BlockingBars())
    await started.watch_ohlcv("BTC/USDT", "1m", lambda _: None)
    task = started._ws_task
    assert task is not None
    started.stop_stream()
    with suppress(asyncio.CancelledError):
        await task

    await _fetcher()._watch_ohlcv_raw("BTC/USDT", "1m", lambda _: None)

    class _RawBars:
        def __init__(self, owner: DataFetcher, payload: list[list[Any]]) -> None:
            self.owner = owner
            self.payload = payload

        async def watch_ohlcv(self, symbol: str, timeframe: str) -> list[list[Any]]:
            self.owner._ws_running = False
            return self.payload

    async_owner = _fetcher()
    async_owner._exchange = _RawBars(async_owner, [[1, 1, 2, 0, 1, 3]])
    async_owner._ws_running = True
    received_async: list[list[list[Any]]] = []

    async def async_callback(payload: list[list[Any]]) -> None:
        received_async.append(payload)

    await async_owner._watch_ohlcv_raw("BTC/USDT", "1m", async_callback)
    assert received_async

    sync_owner = _fetcher()
    sync_owner._exchange = _RawBars(sync_owner, [[2, 1, 2, 0, 1, 3]])
    sync_owner._ws_running = True
    received_sync: list[list[list[Any]]] = []
    await sync_owner._watch_ohlcv_raw("BTC/USDT", "1m", received_sync.append)
    assert received_sync

    empty_owner = _fetcher()
    empty_owner._exchange = _RawBars(empty_owner, [])
    empty_owner._ws_running = True
    await empty_owner._watch_ohlcv_raw("BTC/USDT", "1m", lambda _: None)

    class _BrokenBars:
        async def watch_ohlcv(self, symbol: str, timeframe: str) -> list[list[Any]]:
            raise RuntimeError("websocket down")

    broken = _fetcher(_BrokenBars())
    broken._ws_running = True

    async def stop_after_backoff(_: float) -> None:
        broken._ws_running = False

    monkeypatch.setattr(fetcher_module.asyncio, "sleep", stop_after_backoff)
    await broken._watch_ohlcv_raw("BTC/USDT", "1m", None)


def test_market_meta_converters_limiter_and_symbol_id_fallback() -> None:
    assert _to_float(None, 9.0) == 9.0
    assert _to_float("bad", 9.0) == 9.0
    assert _to_int(None, 9) == 9
    assert _to_int("bad", 9) == 9
    assert _is_retryable(OSError("network"))
    assert not _is_retryable(RuntimeError("permanent"))
    assert RateLimiter(0.3).min_interval == 0.3

    class _ByIdExchange:
        markets: dict[str, Any] = {"other": {"type": "spot"}}
        markets_by_id = {"BTC-USDT-SWAP": [{"type": "swap", "symbol": "BTC/USDT:USDT"}]}

        def market(self, symbol: str) -> dict[str, Any]:
            raise KeyError(symbol)

    fetcher = MarketMetaFetcher(DataConfig(), exchange=_ByIdExchange())
    assert fetcher._resolve_swap_symbol("BTC-USDT-SWAP") == "BTC/USDT:USDT"

    class _BrokenByIdExchange:
        markets: dict[str, Any] = {}

        def market(self, symbol: str) -> dict[str, Any]:
            raise KeyError(symbol)

        @property
        def markets_by_id(self) -> dict[str, Any]:
            raise RuntimeError("lookup unavailable")

    broken = MarketMetaFetcher(DataConfig(), exchange=_BrokenByIdExchange())
    assert broken._resolve_swap_symbol("BTC-USDT-SWAP") == "BTC-USDT-SWAP"


@pytest.mark.asyncio
async def test_market_meta_lifecycle_with_mocked_ccxt(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Exchange:
        def __init__(self, fail: bool = False) -> None:
            self.fail = fail
            self.sandbox = False
            self.closed = False

        def set_sandbox_mode(self, enabled: bool) -> None:
            self.sandbox = enabled

        async def load_markets(self) -> dict[str, Any]:
            if self.fail:
                raise RuntimeError("load failed")
            return {}

        async def close(self) -> None:
            self.closed = True

    injected = _Exchange()
    externally_owned = MarketMetaFetcher(DataConfig(), exchange=injected)
    await externally_owned.connect()
    await externally_owned.disconnect()
    assert not injected.closed

    connected = _Exchange()
    monkeypatch.setattr(meta_module.ccxt, "okx", lambda config: connected)
    owned = MarketMetaFetcher(DataConfig(sandbox=True))
    await owned.connect()
    assert owned._exchange is connected and connected.sandbox
    await owned.disconnect()
    assert connected.closed and owned._exchange is None

    failed = _Exchange(fail=True)
    monkeypatch.setattr(meta_module.ccxt, "okx", lambda config: failed)
    with pytest.raises(GatewayConnectionError, match="load failed"):
        await MarketMetaFetcher(DataConfig()).connect()
    assert failed.closed


@pytest.mark.asyncio
async def test_market_meta_history_invalid_entries_and_oi_warning_boundary() -> None:
    class _HistoryExchange:
        markets: dict[str, Any] = {}
        markets_by_id: dict[str, Any] = {}

        def market(self, symbol: str) -> dict[str, Any]:
            raise KeyError(symbol)

        async def fetchFundingRateHistory(self, *args: Any) -> list[dict[str, Any]]:
            return [{"timestamp": "invalid"}]

        async def fetchOpenInterestHistory(self, *args: Any) -> list[dict[str, Any]]:
            return [
                {"timestamp": "invalid"},
                {"timestamp": 101, "openInterestAmount": 4.0},
            ]

    fetcher = MarketMetaFetcher(DataConfig(), exchange=_HistoryExchange())
    funding = await fetcher.fetch_funding_rate_history("BTC/USDT", since_ms=100)
    assert funding.empty
    oi = await fetcher.fetch_open_interest_history("BTC/USDT", since_ms=100, end_ms=200)
    assert oi["timestamp"].tolist() == [101]

    future = OpenInterestSnapshot("BTC/USDT", 1.0, 1.0, 1.0, 1, 10_000)
    assert not is_oi_fresh(future, now_ms=9_999)


# ---------------------------------------------------------------------------
# Round-2 closure: fetcher.py `if callback is not None:` False branch and
# market_meta_fetcher.py natural pagination exhaustion (353->388).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watch_trades_loop_frame_without_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-empty trade frame with callback=None must still exit the loop."""

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(fetcher_module.asyncio, "sleep", no_sleep)

    class _FrameWs:
        def __init__(self, owner: DataFetcher) -> None:
            self.owner = owner

        async def watch_trades(self, symbol: str) -> list[dict[str, Any]]:
            self.owner._ws_running = False
            return [{"timestamp": 7, "price": 8.0, "amount": 9.0, "side": "buy"}]

    fetcher = _fetcher()
    fetcher._exchange = _FrameWs(fetcher)
    fetcher._ws_running = True
    await fetcher._watch_trades_loop("BTC/USDT", None, limit=1, poll_fallback_interval_s=0)
    assert not fetcher._ws_running


@pytest.mark.asyncio
async def test_market_meta_funding_history_pagination_exhausts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full pages for the whole (reduced) page budget -> loop exhausts naturally.

    Exercises the ``for _ in range(MAX_HISTORY_PAGES)`` exit edge (353->388)
    which a short page / empty page ``break`` never covers.
    """

    class _PagedFunding:
        def __init__(self) -> None:
            self.calls = 0

        async def fetchFundingRateHistory(
            self, symbol: str, since: int, limit: int, params: Any
        ) -> list[dict[str, Any]]:
            self.calls += 1
            base = int(since)
            return [
                {
                    "timestamp": base + i * 3_600_000,
                    "fundingRate": 0.0001,
                    "info": {
                        "realizedRate": 0.0002,
                        "fundingTime": base + i * 3_600_000,
                    },
                }
                for i in range(limit)
            ]

    exchange = _PagedFunding()
    monkeypatch.setattr(meta_module, "MAX_HISTORY_PAGES", 2)
    fetcher = MarketMetaFetcher(DataConfig(), exchange=exchange)
    df = await fetcher.fetch_funding_rate_history("BTC/USDT", since_ms=0, limit=3)
    assert len(df) == 6  # 2 pages x 3 rows, no early break
    assert exchange.calls == 2
