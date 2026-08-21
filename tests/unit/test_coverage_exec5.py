"""Coverage completion for quantflow/execution (round 5).

Targets the remaining uncovered lines/branches (baseline):
- engine.py            93%  (ws push exception, ws fill stamping, stop CancelledError,
                             router property, kill-switch gate, rejection event, 594-599)
- okx_gateway.py       75%  (clientOrderId, filled/partial stamps, timeouts, open orders,
                             health-monitor seams, spot branches, ws loop exits/backoff)
- exchange_health.py   92%  (empty-window should_trip, fail-soft sink/bus paths, close circuit)
- gateway_base.py      97%  (OpenOrder.__repr__)
- kill_switch.py       99%  (activate with empty reason)
- order_manager.py     96%  (eviction exhaust, non-terminal update, ghost timeout, cancel guards)
- paper_gateway.py     95%  (reduceOnly same-direction, orderbook extra slip, open orders,
                             invalid BBO, stale BBO, position flip)

No network / no real IO — all external seams are mocked.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from quantflow.common.event_bus import EventBus
from quantflow.common.models import (
    Order,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
)
from quantflow.execution import okx_gateway as okx_mod
from quantflow.execution.engine import ExecutionEngine
from quantflow.execution.exchange_health import ExchangeHealthMonitor
from quantflow.execution.gateway_base import GatewayBase, GatewayError, OpenOrder
from quantflow.execution.kill_switch import KillSwitch
from quantflow.execution.okx_gateway import OKXGateway
from quantflow.execution.order_manager import MAX_TRACKED_ORDERS, OrderManager
from quantflow.execution.order_router import OrderRouter
from quantflow.execution.paper_gateway import PaperGateway

# --------------------------------------------------------------------------- #
# engine.py
# --------------------------------------------------------------------------- #


class _NoopGateway(GatewayBase):
    async def connect(self, config: dict[str, Any] | None = None) -> None:
        pass

    async def send_order(self, order: Order) -> str:
        return "ex-1"

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        return True

    async def query_positions(self) -> list[Any]:
        return []

    async def query_open_orders(self, symbol: str) -> list[OpenOrder]:
        return []


class _FillGateway(_NoopGateway):
    async def send_order(self, order: Order) -> str:
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.filled_price = float(order.price or 100.0)
        return "ex-1"


class _RejectingGateway(_NoopGateway):
    async def send_order(self, order: Order) -> str:
        raise RuntimeError("gateway exploded")


class _CancelledDisconnectGateway(_NoopGateway):
    async def disconnect(self) -> None:
        raise asyncio.CancelledError()


class _FailingQueryGateway(_NoopGateway):
    async def query_positions(self) -> list[Any]:
        raise GatewayError("query failed")


def _buy_order(price: float = 100.0, qty: float = 1.0) -> Order:
    return Order(
        order_id="",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type="market",
        quantity=qty,
        price=price,
        strategy_id="cov5",
    )


def _track_pending(engine: ExecutionEngine, oid: str) -> None:
    engine._order_mgr.track(
        OrderRequest(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="limit",
            quantity=1.0,
            price=100.0,
            strategy_id="cov5",
        ),
        OrderResult(order_id=oid, status=OrderStatus.SUBMITTED, symbol="BTC/USDT", side="buy"),
    )


@pytest.mark.asyncio
async def test_engine_on_order_update_swallows_malformed_push() -> None:
    """A malformed ws push (bad ``filled``) must not kill the stream consumer."""
    engine = ExecutionEngine(gateway=_NoopGateway())
    _track_pending(engine, "oid-1")
    # status=open, filled is unparseable → float() raises inside _apply_order_update
    await engine._on_order_update([{"id": "oid-1", "status": "open", "filled": "boom"}])
    tracked = engine.order_manager.get_order("oid-1")
    assert tracked is not None
    assert tracked.status == OrderStatus.SUBMITTED


@pytest.mark.asyncio
async def test_engine_ws_fill_without_average_price() -> None:
    """A fill push with average<=0 takes the 237->239 False branch (no stamp)."""
    engine = ExecutionEngine(gateway=_NoopGateway())
    _track_pending(engine, "oid-1")
    await engine._apply_order_update({"id": "oid-1", "status": "open", "filled": 0.5})
    tracked = engine.order_manager.get_order("oid-1")
    assert tracked is not None
    assert tracked.status == OrderStatus.PARTIAL
    assert tracked.filled_price == 0.0  # average absent → not stamped


@pytest.mark.asyncio
async def test_engine_ws_fill_stamps_average_price_and_fee() -> None:
    """closed push with average>0 and fee.cost stamps the tracked order and fills."""
    engine = ExecutionEngine(gateway=_NoopGateway())
    _track_pending(engine, "oid-1")
    await engine._apply_order_update(
        {
            "id": "oid-1",
            "status": "closed",
            "filled": 0.5,
            "average": 100.0,
            "fee": {"cost": 1.5},
        }
    )
    tracked = engine.order_manager.get_order("oid-1")
    assert tracked is not None
    assert tracked.status == OrderStatus.FILLED
    assert tracked.filled_price == 100.0
    assert tracked.fee == 1.5


@pytest.mark.asyncio
async def test_engine_stop_re_raises_cancelled_error() -> None:
    """stop() propagates CancelledError from a racing gateway teardown."""
    engine = ExecutionEngine(gateway=_CancelledDisconnectGateway())
    with pytest.raises(asyncio.CancelledError):
        await engine.stop()


def test_engine_router_property_exposes_order_router() -> None:
    engine = ExecutionEngine(gateway=None)
    assert isinstance(engine.router, OrderRouter)


@pytest.mark.asyncio
async def test_engine_submit_rejects_when_kill_switch_active() -> None:
    ks = KillSwitch(_NoopGateway())
    await ks.activate("manual-stop")
    engine = ExecutionEngine(gateway=_FillGateway(), kill_switch=ks)
    result = await engine.submit(_buy_order())
    assert result.status == OrderStatus.REJECTED


@pytest.mark.asyncio
async def test_engine_submit_publishes_rejection_event_with_bus() -> None:
    """route() failure with an event bus publishes the REJECTED order event."""
    bus = EventBus()
    engine = ExecutionEngine(gateway=_RejectingGateway(), event_bus=bus)
    order = _buy_order()
    order.order_id = "local-pre"
    result = await engine.submit(order)
    assert result.status == OrderStatus.REJECTED


@pytest.mark.asyncio
async def test_engine_submit_filled_tracked_is_none_skips_mirror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tracked copy missing (get_order→None) takes the skip branch (432->435)."""
    engine = ExecutionEngine(gateway=_FillGateway())
    monkeypatch.setattr(engine._order_mgr, "get_order", lambda oid: None)
    result = await engine.submit(_buy_order())
    assert result.status == OrderStatus.FILLED


@pytest.mark.asyncio
async def test_engine_sync_positions_fail_closed_on_gateway_error() -> None:
    """GatewayError from query_positions keeps last-known state, returns False."""
    engine = ExecutionEngine(gateway=_FailingQueryGateway())
    assert await engine.sync_positions() is False


# --------------------------------------------------------------------------- #
# okx_gateway.py
# --------------------------------------------------------------------------- #


class _FakeExchange:
    """Configurable ccxt async exchange double (no network)."""

    def __init__(self) -> None:
        self.markets: dict[str, object] = {"BTC/USDT": {}}
        self.sandbox_mode = False
        self.closed = False
        self.create_result: dict[str, Any] = {
            "id": "oid-1",
            "filled": "0",
            "average": None,
            "fee": None,
        }
        self.create_raises: BaseException | None = None
        self.cancel_raises: BaseException | None = None
        self.cancel_all_raises: BaseException | None = None
        self.open_orders_payload: list[dict[str, Any]] = []
        self.open_orders_raises: BaseException | None = None
        self.positions_payload: list[dict[str, Any]] = []
        self.positions_raises: BaseException | None = None
        self.balance_payload: dict[str, Any] = {}
        self.balance_raises: BaseException | None = None
        self.ticker_payload: dict[str, Any] = {"last": "100.0"}
        self.ticker_raises: BaseException | None = None
        self.watch_ohlcv_raises: BaseException | None = None
        self.watch_ohlcv_calls = 0
        self.watch_orders_result: list[dict[str, Any]] | None = None
        self.watch_orders_raises: BaseException | None = None
        self.watch_orders_calls = 0
        self.watch_symbol: Any = "sentinel"
        self.close_raises: BaseException | None = None
        self.create_kwargs: list[dict[str, Any]] = []

    def set_sandbox_mode(self, enabled: bool) -> None:
        self.sandbox_mode = enabled

    async def load_markets(self) -> dict[str, object]:
        return self.markets

    async def close(self) -> None:
        if self.close_raises is not None:
            raise self.close_raises
        self.closed = True

    async def create_order(self, **kwargs: Any) -> dict[str, Any]:
        self.create_kwargs.append(kwargs)
        if self.create_raises is not None:
            raise self.create_raises
        return self.create_result

    async def cancel_order(self, order_id: str, symbol: str) -> None:
        if self.cancel_raises is not None:
            raise self.cancel_raises

    async def cancel_all_orders(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        if self.cancel_all_raises is not None:
            raise self.cancel_all_raises
        return []

    async def fetch_open_orders(self, symbol: str = "") -> list[dict[str, Any]]:
        if self.open_orders_raises is not None:
            raise self.open_orders_raises
        return self.open_orders_payload

    async def fetch_positions(self) -> list[dict[str, Any]]:
        if self.positions_raises is not None:
            raise self.positions_raises
        return self.positions_payload

    async def fetch_balance(self) -> dict[str, Any]:
        if self.balance_raises is not None:
            raise self.balance_raises
        return self.balance_payload

    async def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        if self.ticker_raises is not None:
            raise self.ticker_raises
        return self.ticker_payload

    async def watch_ohlcv(self, symbol: str, timeframe: str) -> list[Any]:
        self.watch_ohlcv_calls += 1
        if self.watch_ohlcv_raises is not None:
            raise self.watch_ohlcv_raises
        return [[1, 100.0, 100.0, 100.0, 100.0, 0.0]]

    async def watch_orders(self, symbol: str | None) -> list[dict[str, Any]]:
        self.watch_orders_calls += 1
        self.watch_symbol = symbol
        if self.watch_orders_raises is not None:
            raise self.watch_orders_raises
        return self.watch_orders_result or []


class _HealthMonitor:
    """Records health-monitor seam calls."""

    def __init__(self) -> None:
        self.successes = 0
        self.api_errors: list[str | None] = []
        self.rate_limited = 0
        self.ws_disconnects = 0
        self.raise_on_success = False
        self.raise_on_error = False
        self.raise_on_ws = False

    def record_success(self) -> None:
        if self.raise_on_success:
            raise RuntimeError("monitor down")
        self.successes += 1

    def record_api_error(self, code: str | None = None) -> None:
        if self.raise_on_error:
            raise RuntimeError("monitor down")
        self.api_errors.append(code)

    def record_rate_limited(self) -> None:
        self.rate_limited += 1

    def record_ws_disconnect(self) -> None:
        if self.raise_on_ws:
            raise RuntimeError("monitor down")
        self.ws_disconnects += 1


def _gw(exchange: _FakeExchange | None = None, monitor: Any = None) -> OKXGateway:
    gw = OKXGateway(monitoring_sink=None, health_monitor=monitor)
    if exchange is not None:
        gw._exchange = exchange
        gw._connected = True
    return gw


@pytest.mark.asyncio
async def test_okx_disconnect_skips_done_tasks_and_handles_close_error() -> None:
    """disconnect(): a done ws task takes the not-done False branch; close() raising is logged."""
    fake = _FakeExchange()

    async def _finished() -> None:
        return None

    done_task = asyncio.create_task(_finished())
    await done_task
    fake.close_raises = RuntimeError("half-torn session")
    gw = _gw(fake)
    gw._ws_tasks.append(done_task)
    await gw.disconnect()  # close() raising is logged (139-140), state still cleared
    assert gw._exchange is None
    assert gw.is_connected is False

    # sanity: a clean close path also works
    fake2 = _FakeExchange()
    gw2 = _gw(fake2)
    await gw2.disconnect()
    assert fake2.closed is True


@pytest.mark.asyncio
async def test_okx_send_order_injects_client_order_id() -> None:
    """order.order_id + no clientOrderId in params → clientOrderId injected."""
    fake = _FakeExchange()
    gw = _gw(fake)
    order = _buy_order()
    order.order_id = "local-9"
    oid = await gw.send_order(order)
    assert oid == "oid-1"
    assert fake.create_kwargs[-1]["params"]["clientOrderId"] == "local-9"


@pytest.mark.asyncio
async def test_okx_send_order_marks_filled_and_partial() -> None:
    fake = _FakeExchange()
    gw = _gw(fake)

    fake.create_result = {"id": "x1", "filled": "1.0", "average": "50000", "fee": {"cost": "1.2"}}
    order = _buy_order(price=50000.0, qty=1.0)
    await gw.send_order(order)
    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == 1.0
    assert order.filled_price == 50000.0
    assert order.fee == 1.2

    fake.create_result = {"id": "x2", "filled": "0.4", "average": "50000", "fee": None}
    partial = _buy_order(price=50000.0, qty=1.0)
    await gw.send_order(partial)
    assert partial.status == OrderStatus.PARTIAL
    assert partial.filled_quantity == 0.4


@pytest.mark.asyncio
async def test_okx_send_order_timeout_raises_gateway_error() -> None:
    fake = _FakeExchange()
    fake.create_raises = TimeoutError("slow")
    monitor = _HealthMonitor()
    gw = _gw(fake, monitor)
    with pytest.raises(GatewayError, match="create_order timed out"):
        await gw.send_order(_buy_order())
    assert gw.is_connected is False
    assert monitor.api_errors == ["timeout"]


@pytest.mark.asyncio
async def test_okx_cancel_order_timeout_raises_gateway_error() -> None:
    fake = _FakeExchange()
    fake.cancel_raises = TimeoutError("slow")
    gw = _gw(fake)
    with pytest.raises(GatewayError, match="cancel_order timed out"):
        await gw.cancel_order("o1", "BTC/USDT")


@pytest.mark.asyncio
async def test_okx_cancel_all_orders_timeout_raises_gateway_error() -> None:
    fake = _FakeExchange()
    fake.cancel_all_raises = TimeoutError("slow")
    gw = _gw(fake)
    with pytest.raises(GatewayError, match="cancel_all_orders timed out"):
        await gw.cancel_all_orders()


@pytest.mark.asyncio
async def test_okx_query_open_orders_not_connected() -> None:
    gw = OKXGateway()
    with pytest.raises(GatewayError, match="not connected"):
        await gw.query_open_orders("BTC/USDT")


@pytest.mark.asyncio
async def test_okx_query_open_orders_success_skips_malformed() -> None:
    fake = _FakeExchange()
    fake.open_orders_payload = [
        {
            "id": "o1",
            "symbol": "BTC/USDT",
            "side": "buy",
            "type": "limit",
            "price": "100",
            "filled": "0.5",
            "status": "open",
            "timestamp": "123",
        },
        {"id": "o2", "price": "bad"},  # float() raises → skipped
    ]
    gw = _gw(fake)
    orders = await gw.query_open_orders("BTC/USDT")
    assert len(orders) == 1
    assert orders[0].id == "o1"
    assert orders[0].filled_amount == 0.5


@pytest.mark.asyncio
async def test_okx_query_open_orders_timeout_and_error() -> None:
    fake = _FakeExchange()
    fake.open_orders_raises = TimeoutError("slow")
    gw = _gw(fake)
    with pytest.raises(GatewayError, match="fetch_open_orders timed out"):
        await gw.query_open_orders("BTC/USDT")

    fake2 = _FakeExchange()
    fake2.open_orders_raises = RuntimeError("boom")
    gw2 = _gw(fake2)
    with pytest.raises(GatewayError, match="fetch_open_orders failed"):
        await gw2.query_open_orders("BTC/USDT")


@pytest.mark.asyncio
async def test_okx_record_disconnect_shutdown_skips_health_error() -> None:
    monitor = _HealthMonitor()
    gw = _gw(_FakeExchange(), monitor)
    gw._record_disconnect("shutdown")
    assert monitor.api_errors == []
    gw._record_disconnect("timeout")
    assert monitor.api_errors == ["timeout"]


@pytest.mark.asyncio
async def test_okx_health_record_success_and_failure_seams() -> None:
    monitor = _HealthMonitor()
    gw = _gw(_FakeExchange(), monitor)
    gw._health_record_success()
    assert monitor.successes == 1

    monitor.raise_on_success = True
    gw._health_record_success()  # swallowed (433-434)

    monitor2 = _HealthMonitor()
    monitor2.raise_on_error = True
    gw2 = _gw(_FakeExchange(), monitor2)
    gw2._health_record_error(e=RuntimeError("boom"))  # record_api_error raises → 457-458


@pytest.mark.asyncio
async def test_okx_health_record_error_rate_limit_and_generic() -> None:
    monitor = _HealthMonitor()
    gw = _gw(_FakeExchange(), monitor)

    class _NamedError(Exception):
        def __init__(self, name: str) -> None:
            super().__init__("boom")
            self.name = name

    # e=None → generic with code=None
    gw._health_record_error()
    assert monitor.api_errors == [None]
    # 50011 in message → rate limited
    gw._health_record_error(e=RuntimeError("50011 Too Many Requests"))
    assert monitor.rate_limited == 1
    # ccxt-style name → rate limited
    gw._health_record_error(e=_NamedError("RateLimitExceeded"))
    assert monitor.rate_limited == 2
    # auth error name → generic api error with label
    gw._health_record_error(e=_NamedError("AuthenticationError"))
    assert monitor.api_errors[-1] == "AuthenticationError"
    # code override on generic path
    gw._health_record_error(code="foo")
    assert monitor.api_errors[-1] == "foo"


@pytest.mark.asyncio
async def test_okx_health_record_ws_disconnect_seam() -> None:
    monitor = _HealthMonitor()
    gw = _gw(_FakeExchange(), monitor)
    gw._health_record_ws_disconnect()
    assert monitor.ws_disconnects == 1
    monitor.raise_on_ws = True
    gw._health_record_ws_disconnect()  # swallowed (465-466)


@pytest.mark.asyncio
async def test_okx_swap_positions_timeout_malformed_nonfinite() -> None:
    fake = _FakeExchange()
    fake.positions_raises = TimeoutError("slow")
    gw = _gw(fake)
    gw._market_type = "swap"
    with pytest.raises(GatewayError, match="fetch_positions timed out"):
        await gw.query_positions()

    fake2 = _FakeExchange()
    fake2.positions_payload = [
        {
            "symbol": "BTC/USDT",
            "contracts": "bad",
            "entryPrice": "1",
            "markPrice": "1",
            "unrealizedPnl": "1",
        },
        {
            "symbol": "ETH/USDT",
            "contracts": "nan",
            "entryPrice": "1",
            "markPrice": "1",
            "unrealizedPnl": "1",
        },
        {
            "symbol": "SOL/USDT",
            "contracts": "2",
            "entryPrice": "10",
            "markPrice": "11",
            "unrealizedPnl": "2",
        },
    ]
    gw2 = _gw(fake2)
    gw2._market_type = "swap"
    positions = await gw2.query_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "SOL/USDT"


@pytest.mark.asyncio
async def test_okx_spot_positions_timeout() -> None:
    fake = _FakeExchange()
    fake.balance_raises = TimeoutError("slow")
    gw = _gw(fake)
    gw._market_type = "spot"
    with pytest.raises(GatewayError, match="fetch_balance timed out"):
        await gw.query_positions()


@pytest.mark.asyncio
async def test_okx_spot_positions_bad_balance_buckets() -> None:
    fake = _FakeExchange()
    fake.balance_payload = {"total": "not-a-dict", "free": {"BTC": "abc"}, "used": {"ETH": "nan"}}
    gw = _gw(fake)
    gw._market_type = "spot"
    assert await gw.query_positions() == []


@pytest.mark.asyncio
async def test_okx_spot_positions_ticker_error_and_nonfinite() -> None:
    fake = _FakeExchange()
    fake.balance_payload = {"total": {"BTC": "1.0"}}
    fake.ticker_raises = RuntimeError("no ticker")
    gw = _gw(fake)
    gw._market_type = "spot"
    positions = await gw.query_positions()
    assert positions[0].current_price == 0.0

    fake2 = _FakeExchange()
    fake2.balance_payload = {"total": {"BTC": "1.0"}}
    fake2.ticker_payload = {"last": "nan"}
    gw2 = _gw(fake2)
    gw2._market_type = "spot"
    positions2 = await gw2.query_positions()
    assert positions2[0].current_price == 0.0


@pytest.mark.asyncio
async def test_okx_watch_ohlcv_loop_backoff_then_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_sleep = asyncio.sleep

    async def _no_sleep(_seconds: float) -> None:
        await real_sleep(0)  # yield so the stopper task can run

    monkeypatch.setattr(okx_mod.asyncio, "sleep", _no_sleep)
    fake = _FakeExchange()
    fake.watch_ohlcv_raises = RuntimeError("ws down")
    gw = _gw(fake)

    async def _stop_after_two() -> None:
        for _ in range(200):
            await asyncio.sleep(0)
            if fake.watch_ohlcv_calls >= 2:
                gw._running = False
                return

    stopper = asyncio.create_task(_stop_after_two())
    await gw._watch_ohlcv_loop(None)  # exits when _running flips False (621->exit, 642)
    await stopper


@pytest.mark.asyncio
async def test_okx_watch_ohlcv_loop_exits_when_not_running() -> None:
    fake = _FakeExchange()
    gw = _gw(fake)
    gw._running = False
    await gw._watch_ohlcv_loop(None)  # while-condition False on entry → 621->exit


@pytest.mark.asyncio
async def test_okx_watch_orders_loop_empty_and_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_sleep = asyncio.sleep

    async def _no_sleep(_seconds: float) -> None:
        await real_sleep(0)  # yield so the stopper task can run

    monkeypatch.setattr(okx_mod.asyncio, "sleep", _no_sleep)
    fake = _FakeExchange()
    fake.watch_orders_result = []
    gw = _gw(fake)

    async def _stop_after_two() -> None:
        for _ in range(200):
            await asyncio.sleep(0)
            if fake.watch_orders_calls >= 2:
                gw._running = False
                return

    stopper = asyncio.create_task(_stop_after_two())
    # empty result → `if orders and callback` False (663->668) + backoff reset (668)
    await gw._watch_orders_loop(None, symbol="")
    await stopper


@pytest.mark.asyncio
async def test_okx_watch_orders_loop_async_callback() -> None:
    fake = _FakeExchange()
    fake.watch_orders_result = [{"id": "o1", "status": "open"}]
    gw = _gw(fake)
    received: list[Any] = []

    async def _cb(orders: list[dict[str, Any]]) -> None:
        received.append(orders)
        gw._running = False

    await gw._watch_orders_loop(_cb, symbol="BTC/USDT")  # coroutine callback (664-665)
    assert len(received) == 1
    assert fake.watch_symbol == "BTC/USDT"


@pytest.mark.asyncio
async def test_okx_watch_orders_loop_backoff_then_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_sleep = asyncio.sleep

    async def _no_sleep(_seconds: float) -> None:
        await real_sleep(0)  # yield so the stopper task can run

    monkeypatch.setattr(okx_mod.asyncio, "sleep", _no_sleep)
    fake = _FakeExchange()
    fake.watch_orders_raises = RuntimeError("ws down")
    gw = _gw(fake)

    async def _stop_after_two() -> None:
        for _ in range(200):
            await real_sleep(0)
            if fake.watch_orders_calls >= 2:
                gw._running = False
                return

    stopper = asyncio.create_task(_stop_after_two())
    await gw._watch_orders_loop(None)  # two failures double backoff (679), then exit
    await stopper


# --------------------------------------------------------------------------- #
# exchange_health.py
# --------------------------------------------------------------------------- #


def test_health_should_trip_with_empty_window() -> None:
    """Misconfigured negative window purges immediately → total==0 → no trip."""
    m = ExchangeHealthMonitor(window_seconds=-1.0)
    m.record_api_error()
    assert not m.circuit_open()


class _RaisingSink:
    def record_risk_event(self, event_type: str, severity: str) -> None:
        raise RuntimeError("sink down")

    def send_alert(self, *args: Any, **kwargs: Any) -> None:
        # NOT RuntimeError: _trip catches RuntimeError first (no-loop guard)
        # and would swallow this before the generic except at 216.
        raise ValueError("alert down")


class _RaisingBus:
    def publish(self, event: Any) -> None:
        raise RuntimeError("bus down")


@pytest.mark.asyncio
async def test_health_trip_fail_soft_sink_and_bus() -> None:
    """Trip emits must never raise: sink.record_risk_event / sync send_alert /
    event_bus.publish failures are all swallowed."""
    m = ExchangeHealthMonitor(
        monitoring_sink=_RaisingSink(),  # type: ignore[arg-type]
        event_bus=_RaisingBus(),
    )
    m.record_api_error()  # 1/1 > 0.5 → trip; sink/bus failures swallowed
    assert m.circuit_open()
    await asyncio.sleep(0)  # let any fire-and-forget task settle


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_health_close_circuit_fail_soft_sink() -> None:
    clock = _Clock()
    m = ExchangeHealthMonitor(
        cooldown_seconds=100.0,
        monitoring_sink=_RaisingSink(),  # type: ignore[arg-type]
        clock=clock,
    )
    m.record_api_error()  # trip at t=0
    assert m.circuit_open()
    clock.advance(200.0)
    for _ in range(3):
        m.record_success()  # 3rd success closes the breaker → 248-249 (sink raises)
    assert not m.circuit_open()


# --------------------------------------------------------------------------- #
# gateway_base.py
# --------------------------------------------------------------------------- #


def test_open_order_repr() -> None:
    o = OpenOrder("id-1", "BTC/USDT", "buy", "limit", 100.0, 0.5, "open", 123.0)
    assert repr(o) == "OpenOrder(id=id-1, symbol=BTC/USDT, status=open)"


# --------------------------------------------------------------------------- #
# kill_switch.py
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_kill_switch_activate_with_empty_reason() -> None:
    ks = KillSwitch(_NoopGateway())
    result = await ks.activate("")
    assert result["status"] == "activated"
    assert ks.is_active is True


# --------------------------------------------------------------------------- #
# order_manager.py
# --------------------------------------------------------------------------- #


def test_order_manager_eviction_exhausts_with_all_pending() -> None:
    """>cap non-terminal orders: eviction loop runs to exhaustion, evicted stays 0."""
    om = OrderManager(timeout=30)
    for i in range(MAX_TRACKED_ORDERS + 1):
        om._orders[f"o-{i}"] = Order(
            order_id=f"o-{i}",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="limit",
            quantity=1.0,
            status=OrderStatus.SUBMITTED,
        )
    om._evict_terminal_if_needed()
    assert len(om._orders) == MAX_TRACKED_ORDERS + 1


def test_order_manager_update_non_terminal_status() -> None:
    om = OrderManager(timeout=30)
    om.track(
        OrderRequest(symbol="BTC/USDT", side=OrderSide.BUY, order_type="limit", quantity=1.0),
    )
    oid = next(iter(om._orders))
    om.update(oid, OrderStatus.ACCEPTED, filled_quantity=0.0)  # 194->197 False branch
    assert om._orders[oid].status == OrderStatus.ACCEPTED


def test_order_manager_check_timeouts_with_missing_order() -> None:
    om = OrderManager(timeout=1)
    om._pending["ghost-id"] = 0.0  # no matching _orders entry
    pairs = om.check_timeouts()
    assert pairs == [("ghost-id", "")]


def test_order_manager_check_timeouts_skips_recent_pending() -> None:
    om = OrderManager(timeout=30)
    om.track(
        OrderRequest(symbol="BTC/USDT", side=OrderSide.BUY, order_type="limit", quantity=1.0),
    )
    oid = next(iter(om._orders))
    assert om.check_timeouts() == []  # not yet timed out → continue (218)
    assert om._orders[oid].status == OrderStatus.SUBMITTED


def test_order_manager_cancel_order_rejects_non_submitted() -> None:
    om = OrderManager(timeout=30)
    om.track(
        OrderRequest(symbol="BTC/USDT", side=OrderSide.BUY, order_type="limit", quantity=1.0),
    )
    oid = next(iter(om._orders))
    om.update(oid, OrderStatus.PARTIAL, filled_quantity=0.5)
    ok, reason = om.cancel_order(oid)
    assert ok is False
    assert "Only submitted orders" in reason


# --------------------------------------------------------------------------- #
# paper_gateway.py
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_paper_reduce_only_same_direction_leaves_quantity() -> None:
    gw = PaperGateway()
    await gw.send_order(_buy_order(qty=1.0))
    order = _buy_order(qty=0.5)
    order.params = {"reduceOnly": True}
    await gw.send_order(order)  # buy on a long → 157->164 (no cap)
    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == 0.5


@pytest.mark.asyncio
async def test_paper_orderbook_extra_slippage_applied() -> None:
    gw = PaperGateway({"orderbook_fill_enabled": True, "orderbook_extra_slippage": 0.01})
    gw.update_orderbook("BTC/USDT", 100.0, 101.0)
    order = _buy_order(price=100.0)
    await gw.send_order(order)
    assert order.status == OrderStatus.FILLED
    assert order.filled_price == pytest.approx(101.0 * 1.01)


@pytest.mark.asyncio
async def test_paper_query_open_orders_empty() -> None:
    gw = PaperGateway()
    assert await gw.query_open_orders("BTC/USDT") == []


def test_paper_update_orderbook_ignores_invalid_bbo() -> None:
    gw = PaperGateway()
    gw.update_orderbook("BTC/USDT", "bad", 1.0)  # float() raises → 312-313
    gw.update_orderbook("BTC/USDT", 2.0, 1.0)  # crossed book → ignored
    assert "BTC/USDT" not in gw._bbo


@pytest.mark.asyncio
async def test_paper_stale_bbo_rejects_order() -> None:
    gw = PaperGateway({"orderbook_fill_enabled": True, "bbo_max_age_sec": 60})
    order = _buy_order(price=100.0)
    await gw.send_order(order)  # no BBO yet → stale (333) → REJECTED
    assert order.status == OrderStatus.REJECTED


@pytest.mark.asyncio
async def test_paper_position_flip_rebases_entry_price() -> None:
    gw = PaperGateway({"slippage": 0.0})  # zero slip so fill price == order price
    await gw.send_order(_buy_order(price=100.0, qty=1.0))
    sell = _buy_order(price=90.0, qty=2.0)
    sell.side = OrderSide.SELL
    await gw.send_order(sell)
    pos = gw._positions["BTC/USDT"]
    assert pos.quantity == -1.0
    assert pos.entry_price == 90.0  # flip rebases (385)
