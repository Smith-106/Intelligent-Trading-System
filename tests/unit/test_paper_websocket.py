"""ISS-003: PaperGateway mock WebSocket subscription tests."""

from __future__ import annotations

import asyncio
from typing import Any

from quantflow.common.models import Position
from quantflow.execution.paper_gateway import PaperGateway

# ---------------------------------------------------------------------------
# Tests: subscribe()
# ---------------------------------------------------------------------------


class TestPaperGatewaySubscribe:
    async def test_subscribe_ohlcv_starts_mock_loop(self) -> None:
        """subscribe('ohlcv', cb) spawns a mock loop that emits bars."""
        gateway = PaperGateway()
        await gateway.connect()
        # Seed a position so the mock loop has something to emit
        gateway._positions["BTC/USDT"] = Position(
            symbol="BTC/USDT",
            quantity=1.0,
            entry_price=42000.0,
            current_price=42000.0,
            unrealized_pnl=0.0,
        )
        received: list[Any] = []
        await gateway.subscribe("ohlcv", lambda data: received.append(data))
        # Let the 1-second loop fire at least once
        await asyncio.sleep(1.5)
        assert gateway._ws_task is not None
        assert len(received) >= 1
        # Each emission is [[ts, o, h, l, c, v]]
        bar = received[0]
        assert isinstance(bar, list)
        assert len(bar) == 1
        assert len(bar[0]) == 6
        await gateway.disconnect()

    async def test_subscribe_unsupported_channel_is_noop(self) -> None:
        """subscribe('unknown', cb) does not raise and spawns no task."""
        gateway = PaperGateway()
        await gateway.subscribe("unknown", lambda x: x)
        assert gateway._ws_task is None

    async def test_subscribe_without_callback_is_noop(self) -> None:
        """subscribe('ohlcv') with callback=None does not spawn a task."""
        gateway = PaperGateway()
        await gateway.subscribe("ohlcv")
        assert gateway._ws_task is None

    async def test_subscribe_async_callback(self) -> None:
        """Async callbacks are awaited by the mock loop."""
        gateway = PaperGateway()
        await gateway.connect()
        gateway._positions["ETH/USDT"] = Position(
            symbol="ETH/USDT",
            quantity=10.0,
            entry_price=3000.0,
            current_price=3000.0,
            unrealized_pnl=0.0,
        )
        received: list[Any] = []

        async def async_cb(data: Any) -> None:
            received.append(data)

        await gateway.subscribe("ohlcv", async_cb)
        await asyncio.sleep(1.5)
        assert len(received) >= 1
        await gateway.disconnect()


# ---------------------------------------------------------------------------
# Tests: disconnect() cleanup
# ---------------------------------------------------------------------------


class TestPaperDisconnectCleanup:
    async def test_disconnect_cancels_ws_task(self) -> None:
        """disconnect() cancels any active mock WebSocket task."""
        gateway = PaperGateway()
        await gateway.connect()
        gateway._positions["BTC/USDT"] = Position(
            symbol="BTC/USDT",
            quantity=1.0,
            entry_price=42000.0,
            current_price=42000.0,
            unrealized_pnl=0.0,
        )
        await gateway.subscribe("ohlcv", lambda x: None)
        assert gateway._ws_task is not None
        await gateway.disconnect()
        assert gateway._ws_task is None

    async def test_disconnect_without_subscribe_is_safe(self) -> None:
        """disconnect() with no active task does not raise."""
        gateway = PaperGateway()
        await gateway.connect()
        await gateway.disconnect()  # No task started — should be fine
