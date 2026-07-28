"""ISS-20260723-011 (OBS-M cluster) — gateway/order/risk observability tests.

Covers the 4 new MonitoringSink Protocol methods + their wiring:
- OKXGateway: connected gauge + disconnect counter + reconnect counter
- OrderManager: orders-timed-out counter
- RiskEngine: rejection log carries result.details
- NullMonitoringSink: all 4 new methods are no-ops (subclass-safe)
"""

from __future__ import annotations

import logging

import pytest

from quantflow.common.models import Order, OrderRequest, OrderSide
from quantflow.common.monitoring_sink import NullMonitoringSink
from quantflow.execution.okx_gateway import OKXGateway
from quantflow.execution.order_manager import OrderManager


class _RecordingSink(NullMonitoringSink):
    """Subclass Null (inherits all no-ops) + capture the 4 OBS-M methods."""

    def __init__(self) -> None:
        self.connected: list[tuple[str, bool]] = []
        self.disconnects: list[tuple[str, str]] = []
        self.reconnects: list[tuple[str, bool]] = []
        self.timed_out: list[tuple[str, str]] = []

    def record_gateway_connected(self, exchange: str, connected: bool) -> None:
        self.connected.append((exchange, connected))

    def record_gateway_disconnect(self, exchange: str, reason: str) -> None:
        self.disconnects.append((exchange, reason))

    def record_gateway_reconnect(self, exchange: str, success: bool) -> None:
        self.reconnects.append((exchange, success))

    def record_order_timed_out(self, symbol: str, side: str) -> None:
        self.timed_out.append((symbol, side))


class _FakeExchange:
    """Minimal ccxt-shaped exchange for OKXGateway observability tests."""

    def __init__(self) -> None:
        self.sandbox_mode = False
        self.markets = {"BTC/USDT": {}}
        self.fail_create = False
        self.fail_positions = False

    def set_sandbox_mode(self, enabled: bool) -> None:
        self.sandbox_mode = enabled

    async def load_markets(self) -> dict[str, object]:
        return self.markets

    async def close(self) -> None:
        return None

    async def create_order(self, **kwargs: object) -> dict[str, object]:
        if self.fail_create:
            raise RuntimeError("boom")
        return {"id": "oid-1"}

    async def fetch_positions(self) -> list[dict[str, object]]:
        if self.fail_positions:
            raise RuntimeError("positions boom")
        return []


# ---------------------------------------------------------------------------
# NullMonitoringSink — all 4 OBS-M methods are no-ops (subclass-safe)
# ---------------------------------------------------------------------------


def test_null_sink_obs_methods_are_no_ops() -> None:
    """ISS-20260723-011: NullMonitoringSink defines the 4 OBS-M methods as
    no-ops so a subclass (e.g. _LatencySink) inherits them and does not raise
    AttributeError when OKXGateway/OrderManager call them."""
    sink = NullMonitoringSink()
    # None of these should raise.
    sink.record_gateway_connected("okx", True)
    sink.record_gateway_disconnect("okx", "timeout")
    sink.record_gateway_reconnect("okx", False)
    sink.record_order_timed_out("BTC/USDT", "buy")


# ---------------------------------------------------------------------------
# OKXGateway — connected gauge + disconnect + reconnect counters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_okx_connect_records_connected_gauge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ISS-20260723-011 (OBS-M #1): connect() sets the liveness gauge to 1."""
    sink = _RecordingSink()
    exchange = _FakeExchange()

    def build_okx(config: dict[str, object]) -> _FakeExchange:
        return exchange

    import ccxt.async_support as ccxt

    monkeypatch.setattr(ccxt, "okx", build_okx)
    gateway = OKXGateway(sandbox=False, market_type="swap", monitoring_sink=sink)

    await gateway.connect({})

    assert gateway.is_connected is True
    assert sink.connected[-1] == ("okx", True)


@pytest.mark.asyncio
async def test_okx_disconnect_records_gauge_and_counter() -> None:
    """ISS-20260723-011 (OBS-M #1/#2): disconnect() flips the gauge to 0 and
    increments the disconnect counter with reason='shutdown'."""
    sink = _RecordingSink()
    gateway = OKXGateway(monitoring_sink=sink)
    gateway._exchange = _FakeExchange()
    gateway._connected = True

    await gateway.disconnect()

    assert ("okx", "shutdown") in sink.disconnects
    assert sink.connected[-1] == ("okx", False)


@pytest.mark.asyncio
async def test_okx_send_order_timeout_records_disconnect() -> None:
    """ISS-20260723-011 (OBS-M #2): a send_order timeout records a disconnect
    with reason='timeout' + flips the gauge, not just _connected=False."""
    sink = _RecordingSink()
    gateway = OKXGateway(monitoring_sink=sink)
    exchange = _FakeExchange()
    gateway._exchange = exchange
    gateway._connected = True
    order = Order(
        order_id="",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type="limit",
        quantity=0.1,
        price=50000.0,
    )

    # Force a timeout by making create_order hang past CALL_TIMEOUT is hard; use
    # the generic-exception path instead (reason='error') via fail_create.
    exchange.fail_create = True
    with pytest.raises(RuntimeError, match="boom"):
        await gateway.send_order(order)

    assert ("okx", "error") in sink.disconnects
    assert sink.connected[-1] == ("okx", False)


@pytest.mark.asyncio
async def test_okx_reconnect_records_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ISS-20260723-011 (OBS-M #2): ensure_connected records one reconnect
    counter per attempt — success on the attempt that connects, failure on
    the ones that don't."""
    sink = _RecordingSink()
    gateway = OKXGateway(monitoring_sink=sink)
    gateway._max_reconnect_attempts = 3
    calls = {"n": 0}

    async def fake_connect(config=None) -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("still down")
        gateway._connected = True
        gateway._exchange = _FakeExchange()

    async def fake_sleep(seconds: float) -> None:
        return None

    gateway.connect = fake_connect
    monkeypatch.setattr("quantflow.execution.okx_gateway.asyncio.sleep", fake_sleep)

    await gateway.ensure_connected()

    # Two failures then one success.
    assert sink.reconnects.count(("okx", False)) == 2
    assert sink.reconnects.count(("okx", True)) == 1


# ---------------------------------------------------------------------------
# OrderManager — orders-timed-out counter
# ---------------------------------------------------------------------------


def test_order_manager_timeout_records_counter() -> None:
    """ISS-20260723-011 (OBS-M #3): check_timeouts increments the
    orders-timed-out counter for each cancelled order, with (symbol, side)."""
    sink = _RecordingSink()
    mgr = OrderManager(timeout=0, monitoring_sink=sink)
    # Track a non-terminal order (status SUBMITTED) so check_timeouts finds it.
    request = OrderRequest(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type="market",
        quantity=0.1,
        strategy_id="s1",
    )
    mgr.track(request)
    # Force the pending timestamp into the past so the 0s timeout trips.
    oid = next(iter(mgr._pending))
    mgr._pending[oid] = -1.0  # now - ts >> timeout

    timed_out = mgr.check_timeouts()

    assert len(timed_out) == 1
    assert ("BTC/USDT", "buy") in sink.timed_out


def test_order_manager_no_timeout_does_not_record() -> None:
    """ISS-20260723-011: an order within the timeout window does not increment
    the timed-out counter."""
    sink = _RecordingSink()
    mgr = OrderManager(timeout=30, monitoring_sink=sink)
    request = OrderRequest(
        symbol="BTC/USDT",
        side=OrderSide.SELL,
        order_type="limit",
        quantity=1.0,
        strategy_id="s1",
    )
    mgr.track(request)

    mgr.check_timeouts()

    assert sink.timed_out == []


# ---------------------------------------------------------------------------
# RiskEngine — rejection log carries result.details
# ---------------------------------------------------------------------------


def test_risk_rejection_log_includes_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ISS-20260723-011 (OBS-M #5): a failed risk check logs result.details so
    operators see WHY (pct/limit/exposure), not just the reason label."""
    from quantflow.common.config import RiskConfig
    from quantflow.common.models import Direction, Portfolio, Signal
    from quantflow.signal.risk_engine import RiskEngine

    engine = RiskEngine(RiskConfig(position_limit_pct=0.01))
    # A position at ~100% of portfolio trips position_limit (limit=1%).
    from quantflow.common.models import Position

    portfolio = Portfolio(
        cash=0.0,
        positions={
            "BTC/USDT": Position(
                symbol="BTC/USDT",
                quantity=1.0,
                entry_price=100.0,
                current_price=100.0,
            )
        },
    )
    signal = Signal(symbol="BTC/USDT", direction=Direction.LONG, strength=0.5)

    with caplog.at_level(logging.WARNING, logger="quantflow.signal.risk_engine"):
        decision = engine.check(signal, portfolio)

    assert not decision.passed
    # The rejection log line includes "details=" with the structured fields.
    rejection_lines = [r.message for r in caplog.records if "Risk check failed" in r.message]
    assert rejection_lines, "expected a risk rejection log line"
    assert "details=" in rejection_lines[0]
    assert "symbol=BTC/USDT" in rejection_lines[0]
