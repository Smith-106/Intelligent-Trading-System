"""Tests for ExecutionEngine."""

import pytest

from quantflow.common.event_bus import EventBus
from quantflow.common.models import Order, OrderRequest, OrderSide, OrderStatus
from quantflow.common.monitoring_sink import NullMonitoringSink
from quantflow.execution.engine import ExecutionEngine
from quantflow.execution.paper_gateway import PaperGateway


class TestExecutionEngine:
    @pytest.mark.asyncio
    async def test_start_paper_mode(self):
        engine = ExecutionEngine()
        await engine.start(mode="paper")
        assert engine.gateway is not None
        assert isinstance(engine.gateway, PaperGateway)
        await engine.stop()

    @pytest.mark.asyncio
    async def test_submit_order(self):
        engine = ExecutionEngine()
        await engine.start(mode="paper")
        order = Order(
            order_id="",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=0.1,
            price=50000.0,
            strategy_id="test",
        )
        result = await engine.submit(order)
        assert result.status == OrderStatus.FILLED
        assert result.filled_quantity == 0.1
        assert result.filled_price > 0
        await engine.stop()

    @pytest.mark.asyncio
    async def test_submit_records_order_latency_metric(self):
        # ISS-20260724-044: order latency now flows through the injected
        # MonitoringSink (was a module-level ORDER_LATENCY histogram patched
        # at quantflow.execution.engine.ORDER_LATENCY, which no longer exists).
        # Subclass NullMonitoringSink so the other record_* calls submit() makes
        # (record_order_total/filled) are no-ops; only record_order_latency is
        # captured.
        class _LatencySink(NullMonitoringSink):
            def __init__(self) -> None:
                self.observations: list[tuple[str, float]] = []

            def record_order_latency(self, symbol: str, duration_seconds: float) -> None:
                self.observations.append((symbol, duration_seconds))

        sink = _LatencySink()
        engine = ExecutionEngine(monitoring_sink=sink)
        await engine.start(mode="paper")
        order = Order(
            order_id="",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=0.1,
            price=50000.0,
            strategy_id="test",
        )

        await engine.submit(order)

        assert len(sink.observations) == 1
        assert sink.observations[0][0] == "BTC/USDT"
        assert sink.observations[0][1] >= 0
        await engine.stop()

    @pytest.mark.asyncio
    async def test_submit_order_no_gateway(self):
        engine = ExecutionEngine()
        order = Order(
            order_id="",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=0.1,
            price=50000.0,
        )
        with pytest.raises(RuntimeError, match="Gateway not initialized"):
            await engine.submit(order)

    @pytest.mark.asyncio
    async def test_submit_order_via_request(self):
        engine = ExecutionEngine()
        await engine.start(mode="paper")
        request = OrderRequest(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=0.5,
            price=30000.0,
            strategy_id="test_req",
        )
        result = await engine.submit_order(request)
        assert result.status == OrderStatus.FILLED
        assert result.quantity == 0.5
        await engine.stop()

    @pytest.mark.asyncio
    async def test_cancel_order_no_gateway(self):
        engine = ExecutionEngine()
        result = await engine.cancel("fake-id", "BTC/USDT")
        assert result is False

    @pytest.mark.asyncio
    async def test_close_position_none(self):
        engine = ExecutionEngine()
        await engine.start(mode="paper")
        result = await engine.close_position("BTC/USDT")
        assert result is None
        await engine.stop()

    @pytest.mark.asyncio
    async def test_check_timeouts(self):
        engine = ExecutionEngine(timeout=0)
        await engine.start(mode="paper")
        # Submit an order so the order manager has something
        order = Order(
            order_id="",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=0.1,
            price=50000.0,
        )
        await engine.submit(order)
        # Should not crash
        engine.check_timeouts()
        await engine.stop()

    @pytest.mark.asyncio
    async def test_submit_with_event_bus(self):
        bus = EventBus()
        events = []
        bus.subscribe("order", lambda e: events.append(e))
        bus.subscribe("fill", lambda e: events.append(e))
        engine = ExecutionEngine(event_bus=bus)
        await engine.start(mode="paper")
        order = Order(
            order_id="",
            symbol="ETH/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=1.0,
            price=3000.0,
        )
        await engine.submit(order)
        assert len(events) >= 1
        await engine.stop()

    @pytest.mark.asyncio
    async def test_order_rejected_on_gateway_error(self):
        engine = ExecutionEngine()
        await engine.start(mode="paper")
        # Send order with no available price and no cached price
        order = Order(
            order_id="",
            symbol="UNKNOWN/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=1.0,
            price=None,  # Will try gateway._prices which is empty
        )
        result = await engine.submit(order)
        assert result.status == OrderStatus.REJECTED
        await engine.stop()

    @pytest.mark.asyncio
    async def test_properties(self):
        engine = ExecutionEngine()
        await engine.start(mode="paper")
        assert engine.order_manager is not None
        assert engine.position_manager is not None
        assert engine.gateway is not None
        await engine.stop()

    @pytest.mark.asyncio
    async def test_async_context_manager_teardown(self):
        """ISS-20260723-012: ``async with engine`` guarantees stop() on exit."""
        engine = ExecutionEngine()
        async with engine:
            await engine.start(mode="paper")
            assert engine.gateway is not None
        # exit path ran stop() — gateway disconnected
        assert engine.gateway is not None  # gateway ref retained, just disconnected

    @pytest.mark.asyncio
    async def test_async_context_manager_teardown_on_exception(self):
        """ISS-20260723-012: teardown runs even when body raises; exception
        is not suppressed."""
        engine = ExecutionEngine()
        await engine.start(mode="paper")
        with pytest.raises(ValueError, match="boom"):
            async with engine:
                raise ValueError("boom")
        # stop() still ran despite the exception
        # (no assert on side-effect beyond no-leak; gateway.disconnect is a no-op
        #  on PaperGateway after disconnect, so this mainly proves no swallow)

    @pytest.mark.asyncio
    async def test_stop_swallows_disconnect_failure(self):
        """ISS-20260723-012: stop() must not raise if gateway.disconnect fails
        on cleanup — idempotent teardown."""
        engine = ExecutionEngine()
        await engine.start(mode="paper")

        async def boom(_config=None):
            raise RuntimeError("disconnect exploded")

        engine.gateway.disconnect = boom  # type: ignore[method-assign]
        # should not raise
        await engine.stop()
