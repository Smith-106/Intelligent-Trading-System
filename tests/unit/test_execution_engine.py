"""Tests for ExecutionEngine."""

from typing import Any

import pytest

from quantflow.common.event_bus import EventBus
from quantflow.common.models import Order, OrderRequest, OrderSide, OrderStatus, Position
from quantflow.common.monitoring_sink import NullMonitoringSink
from quantflow.common.validators import POSITION_EPSILON
from quantflow.execution.engine import EVENT_ORDER, ExecutionEngine
from quantflow.execution.gateway_base import GatewayBase, OpenOrder
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


class _RestingLimitGateway(GatewayBase):
    """Gateway that accepts orders but never fills them (live resting limit).

    Optionally stamps a partial fill on submit (``rest_fill``) to emulate an
    OKX limit that partially fills in the create_order REST response.
    """

    def __init__(self, rest_fill: float = 0.0) -> None:
        self._counter = 0
        self._rest_fill = rest_fill
        self.subscribed: list[tuple[str, Any]] = []

    async def connect(self, config: dict[str, Any] | None = None) -> None:
        pass

    async def send_order(self, order: Order) -> str:
        self._counter += 1
        if self._rest_fill > 0:
            order.filled_quantity = self._rest_fill
            order.filled_price = order.price or 0.0
            order.status = OrderStatus.PARTIAL
        return f"ex-{self._counter}"

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        return True

    async def query_positions(self) -> list[Position]:
        return []

    async def query_open_orders(self, symbol: str) -> list[OpenOrder]:
        return []

    async def subscribe(self, channel: str, callback: Any = None) -> None:
        self.subscribed.append((channel, callback))


class TestWsOrderStream:
    """T-s1-02 acceptance: watch_orders → cumulative delta → L4."""

    @staticmethod
    def _limit_order(qty: float = 0.1) -> Order:
        return Order(
            order_id="",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="limit",
            quantity=qty,
            price=50_000.0,
            strategy_id="ws-test",
        )

    @pytest.mark.asyncio
    async def test_cumulative_partial_fills_sum_exactly(self):
        """ws 3 batches (30%→60%→100%): FILLED terminal, L4 deltas sum to
        quantity with zero drift, applied_filled_qty == quantity."""
        gw = _RestingLimitGateway()
        engine = ExecutionEngine(gateway=gw)
        await engine.start(gateway_config={"ws_order_stream": True})
        assert gw.subscribed == [("orders", engine._on_order_update)]

        result = await engine.submit(self._limit_order(0.1))
        assert result.status == OrderStatus.SUBMITTED
        oid = result.order_id
        cb = gw.subscribed[0][1]

        for filled, status in (
            (0.03, "open"),
            (0.06, "open"),
            (0.10, "closed"),
        ):
            await cb([{"id": oid, "status": status, "filled": filled, "average": 50_000.0}])

        tracked = engine.order_manager.get_order(oid)
        assert tracked is not None
        assert tracked.status == OrderStatus.FILLED
        assert tracked.applied_filled_qty == pytest.approx(0.1, abs=POSITION_EPSILON)
        pos = engine.position_manager.get_position("BTC/USDT")
        assert pos is not None
        assert pos.quantity == pytest.approx(0.1, abs=POSITION_EPSILON)
        await engine.stop()

    @pytest.mark.asyncio
    async def test_partial_then_cancel_terminal_guard_rejects_late_fill(self):
        gw = _RestingLimitGateway()
        bus = EventBus()
        events: list[Any] = []
        bus.subscribe(EVENT_ORDER, events.append)
        engine = ExecutionEngine(gateway=gw, event_bus=bus)
        await engine.start(gateway_config={"ws_order_stream": True})

        oid = (await engine.submit(self._limit_order(0.1))).order_id
        cb = gw.subscribed[0][1]
        await cb([{"id": oid, "status": "open", "filled": 0.03, "average": 50_000.0}])
        assert engine.order_manager.get_order(oid).status == OrderStatus.PARTIAL

        await cb([{"id": oid, "status": "canceled", "filled": 0.03}])
        tracked = engine.order_manager.get_order(oid)
        assert tracked.status == OrderStatus.CANCELLED
        assert any(e.data.get("status") == "cancelled" for e in events)

        # Late fill after cancel must be rejected by the terminal-state guard.
        await cb([{"id": oid, "status": "closed", "filled": 0.1, "average": 50_000.0}])
        assert tracked.status == OrderStatus.CANCELLED
        pos = engine.position_manager.get_position("BTC/USDT")
        assert pos is not None
        assert pos.quantity == pytest.approx(0.03, abs=POSITION_EPSILON)
        await engine.stop()

    @pytest.mark.asyncio
    async def test_rest_and_ws_double_report_idempotent(self):
        """create_order REST partial fill + ws re-push of the same cumulative
        value must not double-book L4 (shared applied_filled_qty ledger)."""
        gw = _RestingLimitGateway(rest_fill=0.03)
        engine = ExecutionEngine(gateway=gw)
        await engine.start(gateway_config={"ws_order_stream": True})

        oid = (await engine.submit(self._limit_order(0.1))).order_id
        pos = engine.position_manager.get_position("BTC/USDT")
        assert pos is not None and pos.quantity == pytest.approx(0.03)

        cb = gw.subscribed[0][1]
        # ws re-reports the SAME cumulative fill → zero new delta.
        await cb([{"id": oid, "status": "open", "filled": 0.03, "average": 50_000.0}])
        pos = engine.position_manager.get_position("BTC/USDT")
        assert pos.quantity == pytest.approx(0.03, abs=POSITION_EPSILON)
        await engine.stop()

    @pytest.mark.asyncio
    async def test_ws_order_stream_disabled_by_default(self):
        """Default config → zero behavior change: no subscribe call."""
        gw = _RestingLimitGateway()
        engine = ExecutionEngine(gateway=gw)
        await engine.start(gateway_config={})
        assert gw.subscribed == []
        await engine.stop()

    @pytest.mark.asyncio
    async def test_gateway_without_subscribe_is_noop(self):
        """ws requested but gateway lacks subscribe() → warning no-op, no raise."""
        engine = ExecutionEngine()
        engine._gateway = object()  # type: ignore[assignment]
        await engine._maybe_start_order_stream({"ws_order_stream": True})  # no raise

    @pytest.mark.asyncio
    async def test_untracked_and_malformed_pushes_ignored(self):
        gw = _RestingLimitGateway()
        engine = ExecutionEngine(gateway=gw)
        await engine.start(gateway_config={"ws_order_stream": True})
        cb = gw.subscribed[0][1]
        # Untracked id + malformed entry — must not raise or book anything.
        await cb(
            [
                {"id": "unknown-99", "status": "closed", "filled": 1.0},
                {"status": "open"},
            ]
        )
        assert engine.position_manager.get_position("BTC/USDT") is None
        await engine.stop()

    @pytest.mark.asyncio
    async def test_rejected_and_expired_mappings(self):
        gw = _RestingLimitGateway()
        engine = ExecutionEngine(gateway=gw)
        await engine.start(gateway_config={"ws_order_stream": True})
        cb = gw.subscribed[0][1]

        oid_a = (await engine.submit(self._limit_order())).order_id
        await cb([{"id": oid_a, "status": "rejected"}])
        assert engine.order_manager.get_order(oid_a).status == OrderStatus.REJECTED

        oid_b = (await engine.submit(self._limit_order())).order_id
        await cb([{"id": oid_b, "status": "expired"}])
        assert engine.order_manager.get_order(oid_b).status == OrderStatus.CANCELLED

        # open with zero fill → no state change, no position.
        oid_c = (await engine.submit(self._limit_order())).order_id
        await cb([{"id": oid_c, "status": "open", "filled": 0.0}])
        assert engine.order_manager.get_order(oid_c).status == OrderStatus.SUBMITTED
        assert engine.position_manager.get_position("BTC/USDT") is None
        await engine.stop()
