"""Additional branch coverage tests for ExecutionEngine."""

from __future__ import annotations

from typing import Any

import pytest

from quantflow.common.event_bus import EventBus
from quantflow.common.models import Order, OrderSide, OrderStatus, Position
from quantflow.execution.engine import EVENT_FILL, EVENT_ORDER, ExecutionEngine
from quantflow.execution.gateway_base import GatewayBase


class _PresetGateway(GatewayBase):
    def __init__(self) -> None:
        self.connected_with: dict[str, Any] | None = None
        self.disconnect_called = False
        self.cancel_result = True
        self.positions: list[Position] = []

    async def connect(self, config: dict[str, Any] | None = None) -> None:
        self.connected_with = config

    async def disconnect(self) -> None:
        self.disconnect_called = True

    async def send_order(self, order: Order) -> str:
        order.status = OrderStatus.ACCEPTED
        return "preset-oid"

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        return self.cancel_result

    async def query_positions(self) -> list[Position]:
        return self.positions


class _FilledGateway(_PresetGateway):
    async def send_order(self, order: Order) -> str:
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.filled_price = order.price or 100.0
        return "filled-oid"


class _ErrorGateway(_PresetGateway):
    async def send_order(self, order: Order) -> str:
        raise RuntimeError("gateway down")


class _RejectedGateway(_PresetGateway):
    async def send_order(self, order: Order) -> str:
        order.status = OrderStatus.REJECTED
        return "rejected-oid"


class TestExecutionEngineExtra:
    @pytest.mark.asyncio
    async def test_start_reuses_injected_gateway(self) -> None:
        gateway = _PresetGateway()
        engine = ExecutionEngine(gateway=gateway)

        await engine.start(mode="paper", gateway_config={"token": "abc"})

        assert gateway.connected_with == {"token": "abc"}

    @pytest.mark.asyncio
    async def test_start_live_and_fallback_modes_select_gateways(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created: list[tuple[str, Any]] = []

        class FakePaperGateway:
            def __init__(self, config: dict[str, Any] | None = None) -> None:
                created.append(("paper", config))

            async def connect(self, config: dict[str, Any] | None = None) -> None:
                return None

            async def disconnect(self) -> None:
                return None

        class FakeOKXGateway:
            def __init__(self, sandbox: bool = True) -> None:
                created.append(("okx", sandbox))

            async def connect(self, config: dict[str, Any] | None = None) -> None:
                return None

            async def disconnect(self) -> None:
                return None

        monkeypatch.setattr("quantflow.execution.engine.PaperGateway", FakePaperGateway)
        monkeypatch.setattr("quantflow.execution.engine.OKXGateway", FakeOKXGateway)

        live_engine = ExecutionEngine()
        await live_engine.start(mode="live", gateway_config={"sandbox": False})

        fallback_engine = ExecutionEngine()
        await fallback_engine.start(mode="sim", gateway_config={"name": "fallback"})

        assert ("okx", False) in created
        assert ("paper", {"name": "fallback"}) in created

    @pytest.mark.asyncio
    async def test_submit_sets_submitted_status_when_gateway_accepts(self) -> None:
        engine = ExecutionEngine(gateway=_PresetGateway())
        await engine.start()
        order = Order(
            order_id="",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=1.0,
            price=100.0,
            strategy_id="accept",
        )

        result = await engine.submit(order)

        assert result.status == OrderStatus.SUBMITTED
        tracked = engine.order_manager.get_order("preset-oid")
        assert tracked is not None
        assert tracked.status == OrderStatus.SUBMITTED

    @pytest.mark.asyncio
    async def test_submit_returns_rejected_on_gateway_exception(self) -> None:
        engine = ExecutionEngine(gateway=_ErrorGateway())
        await engine.start()
        order = Order(
            order_id="",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=1.0,
            price=100.0,
        )

        result = await engine.submit(order)

        assert result.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_submit_tracks_rejected_gateway_status_without_pending_order(self) -> None:
        engine = ExecutionEngine(gateway=_RejectedGateway())
        await engine.start()
        order = Order(
            order_id="",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=1.0,
            price=100.0,
            strategy_id="reject",
        )

        result = await engine.submit(order)

        assert result.status == OrderStatus.REJECTED
        tracked = engine.order_manager.get_order("rejected-oid")
        assert tracked is not None
        assert tracked.status == OrderStatus.REJECTED
        assert engine.order_manager.pending_count == 0
        assert engine.order_manager.get_open_orders() == []

    @pytest.mark.asyncio
    async def test_submit_emits_fill_and_updates_position_for_sell_orders(self) -> None:
        bus = EventBus()
        events: list[str] = []
        bus.subscribe(EVENT_ORDER, lambda e: events.append(e.type))
        bus.subscribe(EVENT_FILL, lambda e: events.append(e.type))
        engine = ExecutionEngine(gateway=_FilledGateway(), event_bus=bus)
        await engine.start()
        order = Order(
            order_id="",
            symbol="ETH/USDT",
            side=OrderSide.SELL,
            order_type="market",
            quantity=2.0,
            price=2500.0,
            strategy_id="filled",
        )

        result = await engine.submit(order)

        assert result.status == OrderStatus.FILLED
        pos = engine.position_manager.get_position("ETH/USDT")
        assert pos is not None
        assert pos.quantity == -2.0
        assert events == [EVENT_ORDER, EVENT_FILL]

    @pytest.mark.asyncio
    async def test_cancel_updates_order_state_only_on_success(self) -> None:
        gateway = _PresetGateway()
        engine = ExecutionEngine(gateway=gateway)
        await engine.start()
        order = Order(
            order_id="",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=1.0,
            price=100.0,
            strategy_id="cancel",
        )
        await engine.submit(order)

        assert await engine.cancel("preset-oid", "BTC/USDT") is True
        assert engine.order_manager.get_order("preset-oid").status == OrderStatus.CANCELLED

        gateway.cancel_result = False
        order2 = Order(
            order_id="",
            symbol="ETH/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=1.0,
            price=100.0,
            strategy_id="cancel2",
        )
        await engine.submit(order2)
        assert await engine.cancel("preset-oid", "ETH/USDT") is False

    @pytest.mark.asyncio
    async def test_close_position_submits_opposing_order_for_long_and_short(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = ExecutionEngine(gateway=_PresetGateway())
        await engine.start()
        captured: list[tuple[str, OrderSide, float]] = []

        async def fake_submit_order(request):
            captured.append((request.symbol, request.side, request.quantity))
            return Order(
                order_id="close",
                symbol=request.symbol,
                side=request.side,
                order_type=request.order_type,
                quantity=request.quantity,
            )

        monkeypatch.setattr(engine, "submit_order", fake_submit_order)
        engine.position_manager.update_position("BTC/USDT", 2.5, 100.0)
        engine.position_manager.update_position("ETH/USDT", -1.5, 200.0)

        await engine.close_position("BTC/USDT")
        await engine.close_position("ETH/USDT")
        assert await engine.close_position("XRP/USDT") is None

        assert captured == [
            ("BTC/USDT", OrderSide.SELL, 2.5),
            ("ETH/USDT", OrderSide.BUY, 1.5),
        ]

    @pytest.mark.asyncio
    async def test_sync_positions_handles_missing_and_existing_gateway(self) -> None:
        engine = ExecutionEngine()
        await engine.sync_positions()

        gateway = _PresetGateway()
        gateway.positions = [
            Position(symbol="BTC/USDT", quantity=1.0, entry_price=100.0, current_price=101.0),
            Position(symbol="ETH/USDT", quantity=-2.0, entry_price=200.0, current_price=198.0),
        ]
        engine = ExecutionEngine(gateway=gateway)
        await engine.start()

        await engine.sync_positions()

        assert engine.position_manager.position_count == 2
        assert engine.position_manager.get_position("ETH/USDT").quantity == -2.0

    def test_update_market_price_refreshes_position_manager_and_gateway_reference_price(
        self,
    ) -> None:
        class _PriceAwareGateway(_PresetGateway):
            def __init__(self) -> None:
                super().__init__()
                self.price_updates: list[tuple[str, float]] = []

            def update_market_price(self, symbol: str, price: float) -> None:
                self.price_updates.append((symbol, price))

        gateway = _PriceAwareGateway()
        engine = ExecutionEngine(gateway=gateway)
        engine.position_manager.update_position("BTC/USDT", 1.0, 100.0)

        engine.update_market_price("BTC/USDT", 123.0)

        position = engine.position_manager.get_position("BTC/USDT")
        assert position is not None
        assert position.current_price == 123.0
        assert gateway.price_updates == [("BTC/USDT", 123.0)]
