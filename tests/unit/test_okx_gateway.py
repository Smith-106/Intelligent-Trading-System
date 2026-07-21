"""Tests for the OKX gateway."""

from __future__ import annotations

import pytest

from quantflow.common.models import Order, OrderSide
from quantflow.execution.okx_gateway import OKXGateway


class _FakeExchange:
    def __init__(self):
        self.sandbox_mode = False
        self.markets: dict[str, object] = {"BTC/USDT": {}, "ETH/USDT": {}}
        self.closed = False
        self.order_requests: list[dict[str, object]] = []
        self.cancel_requests: list[tuple[str, str]] = []
        self.cancel_all_requests: list[dict[str, object]] = []
        self.positions_payload: list[dict[str, object]] = [
            {
                "symbol": "BTC/USDT",
                "contracts": "2",
                "entryPrice": "50000",
                "markPrice": "52000",
                "unrealizedPnl": "4000",
            },
            {
                "symbol": "ETH/USDT",
                "contracts": "0",
                "entryPrice": "3000",
                "markPrice": "2900",
                "unrealizedPnl": "-100",
            },
        ]
        self.fail_create = False
        self.fail_cancel = False
        self.fail_cancel_all = False
        self.fail_positions = False

    def set_sandbox_mode(self, enabled: bool) -> None:
        self.sandbox_mode = enabled

    async def load_markets(self) -> dict[str, object]:
        return self.markets

    async def close(self) -> None:
        self.closed = True

    async def create_order(self, **kwargs: object) -> dict[str, object]:
        if self.fail_create:
            raise RuntimeError("order failed")
        self.order_requests.append(kwargs)
        return {"id": "oid-123"}

    async def cancel_order(self, order_id: str, symbol: str) -> None:
        if self.fail_cancel:
            raise RuntimeError("cancel failed")
        self.cancel_requests.append((order_id, symbol))

    async def cancel_all_orders(self, params: dict[str, object]) -> list[dict[str, object]]:
        if self.fail_cancel_all:
            raise RuntimeError("cancel all failed")
        self.cancel_all_requests.append(params)
        return [{"id": "1"}, {"id": "2"}]

    async def fetch_positions(self) -> list[dict[str, object]]:
        if self.fail_positions:
            raise RuntimeError("positions failed")
        return self.positions_payload


@pytest.mark.asyncio
async def test_connect_sets_exchange_and_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    exchange = _FakeExchange()

    def build_okx(config: dict[str, object]) -> _FakeExchange:
        assert config["apiKey"] == "k"
        assert config["secret"] == "s"
        assert config["password"] == "p"
        assert config["enableRateLimit"] is True
        return exchange

    import ccxt.async_support as ccxt

    monkeypatch.setattr(ccxt, "okx", build_okx)
    gateway = OKXGateway(sandbox=False)

    await gateway.connect({"api_key": "k", "secret": "s", "passphrase": "p", "sandbox": True})

    assert gateway.is_connected is True
    assert gateway._exchange is exchange
    assert exchange.sandbox_mode is True


@pytest.mark.asyncio
async def test_disconnect_resets_connection() -> None:
    gateway = OKXGateway()
    exchange = _FakeExchange()
    gateway._exchange = exchange
    gateway._connected = True

    await gateway.disconnect()

    assert gateway.is_connected is False
    assert gateway._exchange is None
    assert exchange.closed is True


@pytest.mark.asyncio
async def test_ensure_connected_returns_when_already_connected() -> None:
    gateway = OKXGateway()
    gateway._exchange = _FakeExchange()
    gateway._connected = True

    await gateway.ensure_connected()

    assert gateway.is_connected is True


@pytest.mark.asyncio
async def test_ensure_connected_retries_until_success(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = OKXGateway()
    gateway._max_reconnect_attempts = 3
    attempts = {"count": 0}

    async def fake_connect(config=None) -> None:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("still down")
        gateway._connected = True
        gateway._exchange = _FakeExchange()

    async def fake_sleep(seconds: float) -> None:
        return None

    gateway.connect = fake_connect
    monkeypatch.setattr("quantflow.execution.okx_gateway.asyncio.sleep", fake_sleep)

    await gateway.ensure_connected()

    assert attempts["count"] == 3
    assert gateway.is_connected is True


@pytest.mark.asyncio
async def test_ensure_connected_stops_after_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = OKXGateway()
    gateway._max_reconnect_attempts = 2
    attempts = {"count": 0}

    async def fake_connect(config=None) -> None:
        attempts["count"] += 1
        raise RuntimeError("still down")

    async def fake_sleep(seconds: float) -> None:
        return None

    gateway.connect = fake_connect
    monkeypatch.setattr("quantflow.execution.okx_gateway.asyncio.sleep", fake_sleep)

    await gateway.ensure_connected()

    assert attempts["count"] == 2
    assert gateway.is_connected is False


@pytest.mark.asyncio
async def test_send_order_requires_connection() -> None:
    gateway = OKXGateway()
    order = Order(
        order_id="",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type="market",
        quantity=0.1,
    )

    with pytest.raises(RuntimeError, match="Not connected"):
        await gateway.send_order(order)


@pytest.mark.asyncio
async def test_send_order_submits_buy_and_sell_orders() -> None:
    gateway = OKXGateway()
    exchange = _FakeExchange()
    gateway._exchange = exchange
    gateway._connected = True

    buy_order = Order(
        order_id="",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type="limit",
        quantity=0.5,
        price=50000,
    )
    sell_order = Order(
        order_id="",
        symbol="ETH/USDT",
        side=OrderSide.SELL,
        order_type="market",
        quantity=1.0,
        price=3000,
    )

    buy_id = await gateway.send_order(buy_order)
    sell_id = await gateway.send_order(sell_order)

    assert buy_id == "oid-123"
    assert sell_id == "oid-123"
    assert exchange.order_requests[0]["side"] == "buy"
    assert exchange.order_requests[1]["side"] == "sell"


@pytest.mark.asyncio
async def test_send_order_marks_connection_down_on_failure() -> None:
    gateway = OKXGateway()
    exchange = _FakeExchange()
    exchange.fail_create = True
    gateway._exchange = exchange
    gateway._connected = True
    order = Order(
        order_id="",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type="limit",
        quantity=0.5,
        price=50000,
    )

    with pytest.raises(RuntimeError, match="order failed"):
        await gateway.send_order(order)

    assert gateway.is_connected is False


@pytest.mark.asyncio
async def test_send_order_rejects_invalid_symbol() -> None:
    """ISS-020: a malformed symbol is rejected at the execution choke point
    before it reaches create_order (whose error body may echo it)."""
    gateway = OKXGateway()
    exchange = _FakeExchange()
    gateway._exchange = exchange
    gateway._connected = True
    order = Order(
        order_id="",
        symbol="BTC' OR '1'='1",  # SQL-injection-shaped symbol
        side=OrderSide.BUY,
        order_type="limit",
        quantity=0.5,
        price=50000,
    )
    with pytest.raises(ValueError):
        await gateway.send_order(order)
    # No order request was forwarded to the exchange.
    assert exchange.order_requests == []


@pytest.mark.asyncio
async def test_cancel_order_rejects_invalid_symbol() -> None:
    """ISS-020: cancel_order validates symbol before forwarding to exchange."""
    gateway = OKXGateway()
    exchange = _FakeExchange()
    gateway._exchange = exchange
    gateway._connected = True
    with pytest.raises(ValueError):
        await gateway.cancel_order("1", "../../etc/passwd")
    assert exchange.cancel_requests == []


@pytest.mark.asyncio
async def test_cancel_order_handles_success_failure_and_missing_exchange() -> None:
    gateway = OKXGateway()
    assert await gateway.cancel_order("1", "BTC/USDT") is False

    exchange = _FakeExchange()
    gateway._exchange = exchange
    assert await gateway.cancel_order("1", "BTC/USDT") is True

    exchange.fail_cancel = True
    assert await gateway.cancel_order("2", "BTC/USDT") is False


@pytest.mark.asyncio
async def test_cancel_all_orders_handles_success_failure_and_missing_exchange() -> None:
    gateway = OKXGateway()
    assert await gateway.cancel_all_orders() == []

    exchange = _FakeExchange()
    gateway._exchange = exchange
    assert await gateway.cancel_all_orders("BTC/USDT") == [True, True]
    assert exchange.cancel_all_requests == [{"symbol": "BTC/USDT"}]

    exchange.fail_cancel_all = True
    assert await gateway.cancel_all_orders() == []


@pytest.mark.asyncio
async def test_query_positions_filters_zero_contracts_and_handles_failures() -> None:
    gateway = OKXGateway()
    assert await gateway.query_positions() == []

    exchange = _FakeExchange()
    gateway._exchange = exchange
    gateway._connected = True
    positions = await gateway.query_positions()

    assert len(positions) == 1
    assert positions[0].symbol == "BTC/USDT"
    assert positions[0].quantity == 2.0
    assert positions[0].entry_price == 50000.0
    assert positions[0].current_price == 52000.0
    assert positions[0].unrealized_pnl == 4000.0

    exchange.fail_positions = True
    failed = await gateway.query_positions()
    assert failed == []
    assert gateway.is_connected is False
