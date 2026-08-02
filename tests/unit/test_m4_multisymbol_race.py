"""Phase 6 M4 integration tests: multi-symbol concurrency and race-condition safety.

Tests cover:
- _signal_lock serialization (max concurrency == 1)
- Per-(strategy, symbol) instance/context isolation
- Multi-symbol routing (distinct instances receive only their own bars)
- Legacy single-symbol backward compatibility
- Concurrent signal reserve/confirm through the full pipeline
"""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
import pytest

from quantflow.common.config import AppConfig
from quantflow.common.models import (
    Bar,
    Direction,
    Order,
    OrderRequest,
    OrderStatus,
    RiskDecision,
    Signal,
)
from quantflow.execution.gateway_base import GatewayBase
from quantflow.strategy.base import StrategyBase, StrategyContext
from quantflow.strategy.engine import TradingSession

# ---------------------------------------------------------------------------
# Local helpers (copied from tests/unit/test_trading_session_extra.py)
# ---------------------------------------------------------------------------


class _Strategy(StrategyBase):
    def __init__(
        self,
        name: str = "s1",
        signal: Signal | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name=name, params=params)
        self._signal = signal
        self.init_calls = 0
        self.bar_calls = 0
        self._bars: list[str] = []  # track symbols received

    def on_init(self, ctx: StrategyContext) -> None:
        self.init_calls += 1

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        self.bar_calls += 1
        self._bars.append(bar.symbol)
        if self._signal is not None:
            ctx.emit_signal(
                symbol=self._signal.symbol,
                direction=self._signal.direction,
                strength=self._signal.strength,
                price=self._signal.price,
                strategy_id=self._signal.strategy_id,
            )

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        return pd.Series(False, index=df.index), pd.Series(False, index=df.index)


class _StatefulStrategy(StrategyBase):
    """Strategy that accumulates bar symbols to test state isolation."""

    def __init__(self, name: str = "stateful", params: dict[str, Any] | None = None) -> None:
        super().__init__(name=name, params=params)
        self._bars: list[str] = []

    def on_init(self, ctx: StrategyContext) -> None:
        pass

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        self._bars.append(bar.symbol)

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        return pd.Series(False, index=df.index), pd.Series(False, index=df.index)


class _FakeGateway(GatewayBase):
    async def connect(self, config: dict[str, Any] | None = None) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def send_order(self, order: Any) -> str:
        return "oid"

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        return True

    async def query_positions(self) -> list[Any]:
        return []

    async def query_open_orders(self, symbol: str) -> list:
        return []


class _FakeKillSwitch:
    def __init__(self, active: bool = False) -> None:
        self.is_active = active
        self.calls: list[str] = []

    async def activate(self, reason: str) -> dict[str, str]:
        self.calls.append(reason)
        self.is_active = True
        return {"status": "activated"}


class _FakeSink:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, object]] = []
        self.portfolio_updates: list[dict[str, float | int]] = []
        self.signals: list[tuple[str, str]] = []
        self.bar_observations: list[tuple[str, float]] = []
        self.signal_observations: list[tuple[str, float]] = []
        self.risk_events: list[tuple[str, str]] = []
        self.kill_switch_activations: list[str] = []
        self.kill_switch_step_failures: list[str] = []
        self.order_totals: list[tuple[str, str, str]] = []
        self.order_filleds: list[tuple[str, str, str]] = []
        self.order_latencies: list[tuple[str, float]] = []
        self.gateway_connected: list[tuple[str, bool]] = []
        self.gateway_disconnects: list[tuple[str, str]] = []
        self.gateway_reconnects: list[tuple[str, bool]] = []
        self.orders_timed_out: list[tuple[str, str]] = []

    def start(self, config: object) -> None:
        return

    def record_signal(self, strategy_id: str, direction: str) -> None:
        self.signals.append((strategy_id, direction))

    def record_bar_latency(self, symbol: str, duration_seconds: float) -> None:
        self.bar_observations.append((symbol, duration_seconds))

    def record_signal_latency(self, strategy_id: str, duration_seconds: float) -> None:
        self.signal_observations.append((strategy_id, duration_seconds))

    def record_portfolio(
        self, total_value: float, cash: float, drawdown: float, n_positions: int
    ) -> None:
        self.portfolio_updates.append(
            {
                "total_value": total_value,
                "cash": cash,
                "drawdown": drawdown,
                "n_positions": n_positions,
            }
        )

    def record_risk_event(self, event_type: str, severity: str) -> None:
        self.risk_events.append((event_type, severity))

    def record_kill_switch_activation(self, reason: str) -> None:
        self.kill_switch_activations.append(reason)

    def record_kill_switch_step_failure(self, step: str) -> None:
        self.kill_switch_step_failures.append(step)

    def record_order_total(self, symbol: str, side: str, strategy_id: str) -> None:
        self.order_totals.append((symbol, side, strategy_id))

    def record_order_filled(self, symbol: str, side: str, strategy_id: str) -> None:
        self.order_filleds.append((symbol, side, strategy_id))

    def record_order_latency(self, symbol: str, duration_seconds: float) -> None:
        self.order_latencies.append((symbol, duration_seconds))

    def record_gateway_connected(self, exchange: str, connected: bool) -> None:
        self.gateway_connected.append((exchange, connected))

    def record_gateway_disconnect(self, exchange: str, reason: str) -> None:
        self.gateway_disconnects.append((exchange, reason))

    def record_gateway_reconnect(self, exchange: str, success: bool) -> None:
        self.gateway_reconnects.append((exchange, success))

    def record_order_timed_out(self, symbol: str, side: str) -> None:
        self.orders_timed_out.append((symbol, side))

    async def send_alert(
        self, message: str, level: str = "warning", extra: dict[str, object] | None = None
    ) -> dict[str, bool]:
        self.sent.append((message, level, extra))
        return {"ok": True}


def _bar(price: float = 100.0, ts: int = 1, symbol: str = "BTC/USDT") -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=ts,
        open=price - 1,
        high=price + 1,
        low=price - 2,
        close=price,
        volume=10.0,
    )


# ---------------------------------------------------------------------------
# Helpers to build a pre-configured session
# ---------------------------------------------------------------------------


def _make_session(
    strategies: list[StrategyBase],
    *,
    sink: _FakeSink | None = None,
) -> TradingSession:
    """Build a TradingSession with stubs wired in (no real execution.start)."""
    config = AppConfig()
    session = TradingSession(config, strategies, monitoring_sink=sink or _FakeSink())
    return session


def _monkeypatch_pipeline(
    session: TradingSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patch update_market_price, update_position, check_drawdown to no-ops."""
    monkeypatch.setattr(
        session.execution.position_manager, "update_market_price", lambda symbol, price: None
    )
    monkeypatch.setattr(session.portfolio, "update_position", lambda symbol, qty, price, **kw: None)
    monkeypatch.setattr(session.portfolio, "check_drawdown", lambda limit: True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSignalLockSerialization:
    """Test 1: _signal_lock ensures max concurrency == 1 in _process_signal_inner."""

    async def test_signal_lock_serializes_concurrent_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = _make_session([_Strategy("alpha")])
        session._running = True

        concurrent_count = 0
        max_concurrent = 0
        lock = asyncio.Lock()

        async def tracking_inner(signal: Signal) -> None:
            nonlocal concurrent_count, max_concurrent
            async with lock:
                concurrent_count += 1
                max_concurrent = max(max_concurrent, concurrent_count)
            # Simulate work
            await asyncio.sleep(0.01)
            async with lock:
                concurrent_count -= 1

        monkeypatch.setattr(session, "_process_signal_inner", tracking_inner)

        signals = [
            Signal(
                symbol=f"SYM{i}",
                direction=Direction.LONG,
                strength=0.5,
                price=100.0,
                strategy_id="alpha",
            )
            for i in range(10)
        ]
        await asyncio.gather(*(session._process_signal(sig) for sig in signals))

        assert max_concurrent == 1, f"Expected max concurrency 1, got {max_concurrent}"


class TestMultiSymbolRouting:
    """Test 2: Distinct instances receive only their own symbol's bars."""

    async def test_two_symbols_route_to_distinct_instances(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        strategy = _StatefulStrategy("router")
        session = _make_session([strategy])

        async def fake_start(mode: str = "paper", gateway_config: Any = None) -> None:
            session.execution._gateway = _FakeGateway()

        monkeypatch.setattr(session.execution, "start", fake_start)
        await session.start(mode="paper", symbols=["BTC/USDT", "ETH/USDT"])

        _monkeypatch_pipeline(session, monkeypatch)

        await session.on_bar(_bar(symbol="BTC/USDT", ts=1))
        await session.on_bar(_bar(symbol="ETH/USDT", ts=2))
        await session.on_bar(_bar(symbol="BTC/USDT", ts=3))

        btc_instance = session._instances.get(("router", "BTC/USDT"))
        eth_instance = session._instances.get(("router", "ETH/USDT"))
        assert btc_instance is not None
        assert eth_instance is not None
        assert btc_instance is not eth_instance
        assert btc_instance._bars == ["BTC/USDT", "BTC/USDT"]
        assert eth_instance._bars == ["ETH/USDT"]


class TestStateIsolation:
    """Test 3: Strategy state (_bars) does not cross-contaminate between symbols."""

    async def test_no_cross_contamination(self, monkeypatch: pytest.MonkeyPatch) -> None:
        strategy = _StatefulStrategy("isolated")
        session = _make_session([strategy])

        async def fake_start(mode: str = "paper", gateway_config: Any = None) -> None:
            session.execution._gateway = _FakeGateway()

        monkeypatch.setattr(session.execution, "start", fake_start)
        await session.start(mode="paper", symbols=["AAA", "BBB"])

        _monkeypatch_pipeline(session, monkeypatch)

        for _ in range(3):
            await session.on_bar(_bar(symbol="AAA", ts=1))
        for _ in range(2):
            await session.on_bar(_bar(symbol="BBB", ts=2))

        aaa_inst = session._instances[("isolated", "AAA")]
        bbb_inst = session._instances[("isolated", "BBB")]
        assert all(s == "AAA" for s in aaa_inst._bars)
        assert all(s == "BBB" for s in bbb_inst._bars)
        assert len(aaa_inst._bars) == 3
        assert len(bbb_inst._bars) == 2


class TestContextKeys:
    """Test 4: _contexts keys are (name, symbol) tuples after start."""

    async def test_contexts_keyed_by_name_symbol(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s1 = _Strategy("alpha")
        s2 = _Strategy("beta")
        session = _make_session([s1, s2])

        async def fake_start(mode: str = "paper", gateway_config: Any = None) -> None:
            session.execution._gateway = _FakeGateway()

        monkeypatch.setattr(session.execution, "start", fake_start)
        await session.start(mode="paper", symbols=["BTC/USDT", "ETH/USDT"])

        expected_keys = {
            ("alpha", "BTC/USDT"),
            ("alpha", "ETH/USDT"),
            ("beta", "BTC/USDT"),
            ("beta", "ETH/USDT"),
        }
        assert set(session._contexts.keys()) == expected_keys
        # Each context is a StrategyContext instance
        for ctx in session._contexts.values():
            assert isinstance(ctx, StrategyContext)


class TestLegacySingleSymbol:
    """Test 5: start(symbols=None) creates (name, '') key; on_bar routes to prototype."""

    async def test_legacy_none_symbols_creates_empty_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        strategy = _Strategy("legacy")
        session = _make_session([strategy])

        async def fake_start(mode: str = "paper", gateway_config: Any = None) -> None:
            session.execution._gateway = _FakeGateway()

        monkeypatch.setattr(session.execution, "start", fake_start)
        await session.start(mode="paper", symbols=None)

        assert ("legacy", "") in session._contexts
        assert session._symbols == []

    async def test_legacy_on_bar_routes_to_prototype(self, monkeypatch: pytest.MonkeyPatch) -> None:
        strategy = _Strategy("legacy")
        session = _make_session([strategy])

        async def fake_start(mode: str = "paper", gateway_config: Any = None) -> None:
            session.execution._gateway = _FakeGateway()

        monkeypatch.setattr(session.execution, "start", fake_start)
        await session.start(mode="paper", symbols=None)

        _monkeypatch_pipeline(session, monkeypatch)

        # on_bar with any symbol should route to the prototype strategy via (name, "") key
        await session.on_bar(_bar(symbol="ANY/SYM", ts=1))
        assert strategy.bar_calls == 1


class _EchoStrategy(StrategyBase):
    """Emits a LONG signal using the bar's own symbol (for multi-symbol tests)."""

    def __init__(self, name: str = "echo", params: dict[str, Any] | None = None) -> None:
        super().__init__(name=name, params=params)

    def on_init(self, ctx: StrategyContext) -> None:
        pass

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        ctx.emit_signal(
            symbol=bar.symbol,
            direction=Direction.LONG,
            strength=0.8,
            price=bar.close,
            strategy_id=self.name,
        )

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        return pd.Series(False, index=df.index), pd.Series(False, index=df.index)


class TestConcurrentSignals:
    """Test 6: Two symbols each emit a signal; both complete through reserve/confirm."""

    async def test_concurrent_signals_reserve_confirm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        strategy = _EchoStrategy("conc")
        session = _make_session([strategy])

        async def fake_start(mode: str = "paper", gateway_config: Any = None) -> None:
            session.execution._gateway = _FakeGateway()

        monkeypatch.setattr(session.execution, "start", fake_start)
        await session.start(mode="paper", symbols=["BTC/USDT", "ETH/USDT"])

        _monkeypatch_pipeline(session, monkeypatch)

        # Monkeypatch pipeline: risk passes, size=10.0, submit returns FILLED
        session._risk_engine.check = lambda signal, portfolio, pending=None: RiskDecision(
            passed=True
        )
        session._position_sizer.size = lambda signal, portfolio, **kw: 10.0

        filled_orders: list[str] = []

        async def fake_submit(request: OrderRequest) -> Order:
            filled_orders.append(request.symbol)
            return Order(
                order_id=f"filled-{request.symbol}",
                symbol=request.symbol,
                side=request.side,
                order_type=request.order_type,
                quantity=request.quantity,
                price=request.price,
                status=OrderStatus.FILLED,
                filled_quantity=request.quantity,
                filled_price=request.price,
                strategy_id=request.strategy_id,
            )

        session.execution.submit_order = fake_submit

        # Feed bars for both symbols — each strategy instance emits its signal
        await session.on_bar(_bar(symbol="BTC/USDT", ts=1))
        await session.on_bar(_bar(symbol="ETH/USDT", ts=2))

        # Both symbols should have been submitted and filled
        assert "BTC/USDT" in filled_orders
        assert "ETH/USDT" in filled_orders
        # Pending should be cleared after confirm
        assert session.portfolio.total_pending_exposure == 0.0
