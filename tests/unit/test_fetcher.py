"""Tests for the CCXT data fetcher."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from quantflow.common.config import DataConfig
from quantflow.common.exceptions import DataError, GatewayConnectionError
from quantflow.data.fetcher import DataFetcher


class _FakeExchange:
    def __init__(
        self,
        *,
        ohlcv_pages: list[list[list[object]]] | None = None,
        watch_batches: list[list[list[object]] | Exception] | None = None,
    ):
        self.ohlcv_pages: list[list[list[object]]] = list(ohlcv_pages or [])
        self.watch_batches: list[list[list[object]] | Exception] = list(watch_batches or [])
        self.fetch_calls: list[dict[str, object]] = []
        self.watch_calls: list[tuple[str, str]] = []
        self.closed = False
        self.sandbox_mode = False
        self.markets: dict[str, object] = {"BTC/USDT": {}}
        self.ticker = {"last": 123.45}

    def set_sandbox_mode(self, enabled: bool) -> None:
        self.sandbox_mode = enabled

    async def load_markets(self) -> dict[str, object]:
        return self.markets

    def parse8601(self, text: str) -> int:
        mapping = {
            "2024-01-01T00:00:00Z": 1_704_067_200_000,
            "2024-01-02T23:59:59Z": 1_704_239_999_000,
        }
        return mapping[text]

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int = 1000,
    ) -> list[list[object]]:
        self.fetch_calls.append(
            {"symbol": symbol, "timeframe": timeframe, "since": since, "limit": limit}
        )
        if self.ohlcv_pages:
            return self.ohlcv_pages.pop(0)
        return []

    async def fetch_ticker(self, symbol: str) -> dict[str, object]:
        return {"symbol": symbol, **self.ticker}

    async def watch_ohlcv(self, symbol: str, timeframe: str) -> list[list[object]]:
        self.watch_calls.append((symbol, timeframe))
        batch = self.watch_batches.pop(0)
        if isinstance(batch, Exception):
            raise batch
        return batch

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def data_config(tmp_path: Path) -> DataConfig:
    return DataConfig(
        parquet_dir=str(tmp_path / "parquet"),
        duckdb_path=str(tmp_path / "db.duckdb"),
        sandbox=True,
        rate_limit=20,
    )


@pytest.mark.asyncio
async def test_connect_success_sets_exchange_and_sandbox(
    monkeypatch: pytest.MonkeyPatch,
    data_config: DataConfig,
) -> None:
    exchange = _FakeExchange()

    def build_okx(config: dict[str, object]) -> _FakeExchange:
        assert config["enableRateLimit"] is True
        assert config["rateLimit"] == 50
        return exchange

    monkeypatch.setattr("quantflow.data.fetcher.ccxt.okx", build_okx)
    fetcher = DataFetcher(data_config)

    await fetcher.connect()

    assert fetcher._exchange is exchange
    assert exchange.sandbox_mode is True


@pytest.mark.asyncio
async def test_connect_wraps_connection_errors(
    monkeypatch: pytest.MonkeyPatch,
    data_config: DataConfig,
) -> None:
    def build_okx(config: dict[str, object]) -> _FakeExchange:
        raise RuntimeError("boom")

    monkeypatch.setattr("quantflow.data.fetcher.ccxt.okx", build_okx)
    fetcher = DataFetcher(data_config)

    with pytest.raises(GatewayConnectionError, match="Failed to connect to OKX: boom"):
        await fetcher.connect()


@pytest.mark.asyncio
async def test_connect_closes_exchange_when_load_markets_fails(
    monkeypatch: pytest.MonkeyPatch,
    data_config: DataConfig,
) -> None:
    class _BrokenExchange(_FakeExchange):
        async def load_markets(self) -> dict[str, object]:
            raise RuntimeError("network down")

    exchange = _BrokenExchange()
    monkeypatch.setattr("quantflow.data.fetcher.ccxt.okx", lambda config: exchange)
    fetcher = DataFetcher(data_config)

    with pytest.raises(GatewayConnectionError, match="Failed to connect to OKX: network down"):
        await fetcher.connect()

    assert exchange.closed is True
    assert fetcher._exchange is None


@pytest.mark.asyncio
async def test_fetch_ohlcv_requires_connection(data_config: DataConfig) -> None:
    fetcher = DataFetcher(data_config)

    with pytest.raises(GatewayConnectionError, match="Not connected"):
        await fetcher.fetch_ohlcv("BTC/USDT")


@pytest.mark.asyncio
async def test_fetch_ohlcv_rejects_invalid_timeframe(data_config: DataConfig) -> None:
    fetcher = DataFetcher(data_config)
    fetcher._exchange = _FakeExchange()

    with pytest.raises(DataError, match="Invalid timeframe"):
        await fetcher.fetch_ohlcv("BTC/USDT", timeframe="2h")


@pytest.mark.asyncio
async def test_fetch_ohlcv_paginates_deduplicates_and_applies_end_filter(
    data_config: DataConfig,
) -> None:
    exchange = _FakeExchange(
        ohlcv_pages=[
            [
                [1_704_067_200_000, 1.0, 2.0, 0.5, 1.5, 10.0],
                [1_704_153_600_000, 1.5, 2.5, 1.0, 2.0, 12.0],
            ],
            [
                [1_704_153_600_000, 1.5, 2.5, 1.0, 2.0, 12.0],
                [1_704_240_000_000, 2.0, 3.0, 1.5, 2.5, 14.0],
            ],
        ]
    )
    fetcher = DataFetcher(data_config)
    fetcher._exchange = exchange

    result = await fetcher.fetch_ohlcv(
        "BTC/USDT",
        timeframe="1d",
        start="2024-01-01",
        end="2024-01-02",
        limit=2,
    )

    assert list(result["timestamp"]) == [1_704_067_200_000, 1_704_153_600_000]
    assert list(result["symbol"].unique()) == ["BTC/USDT"]
    assert list(result["timeframe"].unique()) == ["1d"]
    assert "datetime64[" in str(result["datetime"].dtype)
    assert "UTC" in str(result["datetime"].dtype)
    assert exchange.fetch_calls[0]["since"] == 1_704_067_200_000
    assert exchange.fetch_calls[1]["since"] == 1_704_153_600_001


@pytest.mark.asyncio
async def test_fetch_ohlcv_stops_when_page_smaller_than_limit(data_config: DataConfig) -> None:
    exchange = _FakeExchange(ohlcv_pages=[[[1_704_067_200_000, 1.0, 2.0, 0.5, 1.5, 10.0]]])
    fetcher = DataFetcher(data_config)
    fetcher._exchange = exchange

    result = await fetcher.fetch_ohlcv("BTC/USDT", timeframe="1d", limit=2)

    assert len(result) == 1
    assert len(exchange.fetch_calls) == 1


@pytest.mark.asyncio
async def test_fetch_ohlcv_stops_when_exchange_returns_no_bars(data_config: DataConfig) -> None:
    exchange = _FakeExchange(ohlcv_pages=[[]])
    fetcher = DataFetcher(data_config)
    fetcher._exchange = exchange

    result = await fetcher.fetch_ohlcv("BTC/USDT", timeframe="1d", limit=2)

    assert result.empty
    assert len(exchange.fetch_calls) == 1


@pytest.mark.asyncio
async def test_fetch_ticker_returns_exchange_payload(data_config: DataConfig) -> None:
    fetcher = DataFetcher(data_config)
    fetcher._exchange = _FakeExchange()

    result = await fetcher.fetch_ticker("BTC/USDT")

    assert result["symbol"] == "BTC/USDT"
    assert result["last"] == 123.45


@pytest.mark.asyncio
async def test_fetch_ticker_requires_connection(data_config: DataConfig) -> None:
    fetcher = DataFetcher(data_config)

    with pytest.raises(GatewayConnectionError, match="Not connected"):
        await fetcher.fetch_ticker("BTC/USDT")


def test_get_last_timestamp_success_and_failures(
    monkeypatch: pytest.MonkeyPatch, data_config: DataConfig
) -> None:
    fetcher = DataFetcher(data_config)

    class _QueryResult:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    monkeypatch.setattr("duckdb.query", lambda sql: _QueryResult((1_234_567_890,)))
    assert fetcher.get_last_timestamp("BTC/USDT", "1d", Path("data")) == 1_234_567_890

    monkeypatch.setattr("duckdb.query", lambda sql: _QueryResult((None,)))
    assert fetcher.get_last_timestamp("BTC/USDT", "1d", Path("data")) is None

    def raise_query(sql: str):
        raise RuntimeError("bad parquet")

    monkeypatch.setattr("duckdb.query", raise_query)
    assert fetcher.get_last_timestamp("BTC/USDT", "1d", Path("data")) is None


@pytest.mark.asyncio
async def test_disconnect_stops_stream_and_closes_exchange(data_config: DataConfig) -> None:
    fetcher = DataFetcher(data_config)
    exchange = _FakeExchange()
    fetcher._exchange = exchange
    fetcher._ws_running = True
    fetcher._ws_task = asyncio.create_task(asyncio.sleep(1))

    await fetcher.disconnect()

    assert exchange.closed is True
    assert fetcher._exchange is None
    assert fetcher._ws_running is False
    assert fetcher._ws_task is None


@pytest.mark.asyncio
async def test_stream_bars_requires_connection(data_config: DataConfig) -> None:
    fetcher = DataFetcher(data_config)

    with pytest.raises(GatewayConnectionError, match="Not connected"):
        await fetcher.stream_bars("BTC/USDT")


@pytest.mark.asyncio
async def test_stream_bars_uses_websocket_when_supported(
    monkeypatch: pytest.MonkeyPatch,
    data_config: DataConfig,
) -> None:
    fetcher = DataFetcher(data_config)
    fetcher._exchange = _FakeExchange()
    seen: list[tuple[str, str]] = []

    async def fake_stream_ws(symbol: str, timeframe: str, callback):
        seen.append((symbol, timeframe))

    fetcher._stream_ws = fake_stream_ws

    await fetcher.stream_bars("BTC/USDT", timeframe="1m")
    await asyncio.sleep(0)
    fetcher.stop_stream()

    assert seen == [("BTC/USDT", "1m")]


@pytest.mark.asyncio
async def test_stream_bars_uses_polling_without_watch_method(data_config: DataConfig) -> None:
    fetcher = DataFetcher(data_config)
    fetcher._exchange = SimpleNamespace()
    seen: list[tuple[str, str, float]] = []

    async def fake_stream_poll(symbol: str, timeframe: str, callback, poll_interval: float):
        seen.append((symbol, timeframe, poll_interval))

    fetcher._stream_poll = fake_stream_poll

    await fetcher.stream_bars("BTC/USDT", timeframe="5m", poll_interval=0.25)
    await asyncio.sleep(0)
    fetcher.stop_stream()

    assert seen == [("BTC/USDT", "5m", 0.25)]


@pytest.mark.asyncio
async def test_stream_ws_emits_only_new_bars(data_config: DataConfig) -> None:
    exchange = _FakeExchange(
        watch_batches=[
            [
                [1000, 1.0, 2.0, 0.5, 1.5, 10.0],
                [1000, 1.0, 2.0, 0.5, 1.5, 10.0],
                [2000, 2.0, 3.0, 1.5, 2.5, 12.0],
            ]
        ]
    )
    fetcher = DataFetcher(data_config)
    fetcher._exchange = exchange
    fetcher._ws_running = True
    received: list[dict[str, object]] = []

    def callback(bar: dict[str, object]) -> None:
        received.append(bar)
        if bar["timestamp"] == 2000:
            fetcher._ws_running = False

    await fetcher._stream_ws("BTC/USDT", "1m", callback)

    assert [bar["timestamp"] for bar in received] == [1000, 2000]


@pytest.mark.asyncio
async def test_stream_ws_handles_exceptions_and_retries(
    monkeypatch: pytest.MonkeyPatch,
    data_config: DataConfig,
) -> None:
    exchange = _FakeExchange(watch_batches=[RuntimeError("ws down")])
    fetcher = DataFetcher(data_config)
    fetcher._exchange = exchange
    fetcher._ws_running = True

    async def fake_sleep(seconds: float) -> None:
        fetcher._ws_running = False

    monkeypatch.setattr("quantflow.data.fetcher.asyncio.sleep", fake_sleep)

    await fetcher._stream_ws("BTC/USDT", "1m", None)

    assert exchange.watch_calls == [("BTC/USDT", "1m")]


@pytest.mark.asyncio
async def test_stream_poll_emits_only_new_bars(
    monkeypatch: pytest.MonkeyPatch,
    data_config: DataConfig,
) -> None:
    exchange = _FakeExchange(
        ohlcv_pages=[
            [[1000, 1.0, 2.0, 0.5, 1.5, 10.0]],
            [[1000, 1.0, 2.0, 0.5, 1.5, 10.0]],
            [[2000, 2.0, 3.0, 1.5, 2.5, 12.0]],
        ]
    )
    fetcher = DataFetcher(data_config)
    fetcher._exchange = exchange
    fetcher._ws_running = True
    received: list[dict[str, object]] = []

    async def fake_sleep(seconds: float) -> None:
        if len(received) >= 2:
            fetcher._ws_running = False

    monkeypatch.setattr("quantflow.data.fetcher.asyncio.sleep", fake_sleep)

    def callback(bar: dict[str, object]) -> None:
        received.append(bar)

    await fetcher._stream_poll("BTC/USDT", "1m", callback, poll_interval=0.01)

    assert [bar["timestamp"] for bar in received] == [1000, 2000]


@pytest.mark.asyncio
async def test_stream_poll_handles_exceptions(
    monkeypatch: pytest.MonkeyPatch,
    data_config: DataConfig,
) -> None:
    class _BrokenExchange:
        async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 1):
            raise RuntimeError("poll down")

    fetcher = DataFetcher(data_config)
    fetcher._exchange = _BrokenExchange()
    fetcher._ws_running = True

    async def fake_sleep(seconds: float) -> None:
        fetcher._ws_running = False

    monkeypatch.setattr("quantflow.data.fetcher.asyncio.sleep", fake_sleep)

    await fetcher._stream_poll("BTC/USDT", "1m", None, poll_interval=0.01)


@pytest.mark.asyncio
async def test_stream_helpers_require_connection(data_config: DataConfig) -> None:
    fetcher = DataFetcher(data_config)

    with pytest.raises(GatewayConnectionError, match="Not connected"):
        await fetcher._stream_ws("BTC/USDT", "1m", None)

    with pytest.raises(GatewayConnectionError, match="Not connected"):
        await fetcher._stream_poll("BTC/USDT", "1m", None, 0.01)
