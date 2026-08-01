"""ISS-003: OKXGateway WebSocket subscription tests.

Tests the subscribe(), _watch_ohlcv_loop and _watch_orders_loop methods.
Uses mock exchanges so the tests work regardless of whether ccxt.pro is
installed — the pro-only code path is exercised via duck-typed fakes.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

from quantflow.execution.okx_gateway import OKXGateway

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeProExchange:
    """Mimics a ccxt.okx instance that has ccxt.pro extensions."""

    def __init__(self) -> None:
        self.markets: dict[str, object] = {"BTC/USDT": {}}
        self._ohlcv_payload: list[list[Any]] = [
            [1_700_000_000_000, 42000, 42500, 41800, 42300, 100.0]
        ]
        self._orders_payload: list[dict[str, Any]] = [
            {"id": "1", "symbol": "BTC/USDT", "status": "open"}
        ]
        self.ohlcv_calls = 0
        self.orders_calls = 0
        self.closed = False
        # Control error injection: set to an exception to raise on next call.
        self.raise_on_ohlcv: BaseException | None = None
        self.raise_on_orders: BaseException | None = None

    def set_sandbox_mode(self, enabled: bool) -> None:
        pass

    async def load_markets(self) -> dict[str, object]:
        return self.markets

    async def close(self) -> None:
        self.closed = True

    # ccxt.pro methods — presence of watch_ohlcv triggers hasattr check.
    async def watch_ohlcv(self, symbol: str, timeframe: str) -> list[list[Any]]:
        self.ohlcv_calls += 1
        if self.raise_on_ohlcv is not None:
            exc = self.raise_on_ohlcv
            self.raise_on_ohlcv = None  # Raise once, then succeed
            raise exc
        return self._ohlcv_payload

    async def watch_orders(self, symbol: str) -> list[dict[str, Any]]:
        self.orders_calls += 1
        if self.raise_on_orders is not None:
            exc = self.raise_on_orders
            self.raise_on_orders = None
            raise exc
        return self._orders_payload


def _make_gateway_with_fake(fake: _FakeProExchange) -> OKXGateway:
    """Build an OKXGateway whose internal _exchange is the given fake."""
    gw = OKXGateway(sandbox=True)
    gw._exchange = fake
    gw._connected = True
    return gw


# ---------------------------------------------------------------------------
# Tests: subscribe()
# ---------------------------------------------------------------------------


class TestOKXSubscribe:
    async def test_subscribe_ohlcv_starts_task(self) -> None:
        """subscribe('ohlcv', cb) spawns a background watch task."""
        fake = _FakeProExchange()
        gw = _make_gateway_with_fake(fake)
        received: list[Any] = []
        await gw.subscribe("ohlcv", lambda data: received.append(data))
        assert len(gw._ws_tasks) == 1
        # Let the loop run at least once
        await asyncio.sleep(0.05)
        assert fake.ohlcv_calls >= 1
        assert len(received) >= 1
        await gw.disconnect()

    async def test_subscribe_orders_starts_task(self) -> None:
        """subscribe('orders', cb) spawns a background watch task."""
        fake = _FakeProExchange()
        gw = _make_gateway_with_fake(fake)
        received: list[Any] = []
        await gw.subscribe("orders", lambda data: received.append(data))
        assert len(gw._ws_tasks) == 1
        await asyncio.sleep(0.05)
        assert fake.orders_calls >= 1
        assert len(received) >= 1
        await gw.disconnect()

    async def test_subscribe_unsupported_channel_is_noop(self) -> None:
        """subscribe('unknown', cb) logs a warning but does not raise."""
        fake = _FakeProExchange()
        gw = _make_gateway_with_fake(fake)
        await gw.subscribe("unknown", lambda x: x)
        assert len(gw._ws_tasks) == 0
        await gw.disconnect()

    async def test_subscribe_without_ccxt_pro_is_noop(self) -> None:
        """When exchange has no watch_ohlcv, subscribe is a silent no-op."""
        gw = OKXGateway(sandbox=True)
        # Plain MagicMock without watch_ohlcv attribute
        gw._exchange = MagicMock(spec=[])  # empty spec → no attributes
        gw._connected = True
        await gw.subscribe("ohlcv", lambda x: x)
        assert len(gw._ws_tasks) == 0

    async def test_subscribe_without_callback_is_noop(self) -> None:
        """subscribe('ohlcv') with callback=None does not crash."""
        fake = _FakeProExchange()
        gw = _make_gateway_with_fake(fake)
        await gw.subscribe("ohlcv")  # callback=None default
        # Should still start the task (it just won't call anything)
        await asyncio.sleep(0.05)
        await gw.disconnect()


# ---------------------------------------------------------------------------
# Tests: watch loops — reconnection / backoff
# ---------------------------------------------------------------------------


class TestWatchLoops:
    async def test_watch_ohlcv_reconnects_on_error(self) -> None:
        """After an exception the loop waits backoff seconds and retries."""
        fake = _FakeProExchange()
        fake.raise_on_ohlcv = ConnectionError("boom")
        gw = _make_gateway_with_fake(fake)
        received: list[Any] = []
        await gw.subscribe("ohlcv", lambda data: received.append(data))
        # First call raises → backoff 1s → second call succeeds.
        # We don't wait the full 1s; just verify the error was caught (no crash)
        await asyncio.sleep(0.05)
        # The loop should still be alive (not crashed out)
        assert not gw._ws_tasks[0].done()
        await gw.disconnect()

    async def test_watch_orders_reconnects_on_error(self) -> None:
        fake = _FakeProExchange()
        fake.raise_on_orders = ConnectionError("boom")
        gw = _make_gateway_with_fake(fake)
        await gw.subscribe("orders", lambda data: None)
        await asyncio.sleep(0.05)
        assert not gw._ws_tasks[0].done()
        await gw.disconnect()

    async def test_watch_ohlcv_async_callback(self) -> None:
        """Async callbacks are awaited correctly."""
        fake = _FakeProExchange()
        gw = _make_gateway_with_fake(fake)
        received: list[Any] = []

        async def async_cb(data: Any) -> None:
            received.append(data)

        await gw.subscribe("ohlcv", async_cb)
        await asyncio.sleep(0.05)
        assert len(received) >= 1
        await gw.disconnect()


# ---------------------------------------------------------------------------
# Tests: disconnect() task cleanup
# ---------------------------------------------------------------------------


class TestDisconnectCleanup:
    async def test_disconnect_cancels_ws_tasks(self) -> None:
        """disconnect() sets _running=False and cancels all watch tasks."""
        fake = _FakeProExchange()
        gw = _make_gateway_with_fake(fake)
        await gw.subscribe("ohlcv", lambda x: None)
        await gw.subscribe("orders", lambda x: None)
        assert len(gw._ws_tasks) == 2

        await gw.disconnect()

        assert gw._running is False
        assert len(gw._ws_tasks) == 0
        # The exchange should also be closed
        assert fake.closed is True

    async def test_disconnect_idempotent(self) -> None:
        """Calling disconnect() twice does not raise."""
        fake = _FakeProExchange()
        gw = _make_gateway_with_fake(fake)
        await gw.disconnect()
        await gw.disconnect()  # Second call should be safe
