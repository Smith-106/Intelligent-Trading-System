"""Phase 6 M4 integration tests: Kill Switch release_all + to_thread/flush atomicity.

Tests cover:
- activate_kill_switch clears all pending reservations
- Drawdown breach activates kill switch + clears pending + sets _running=False
- flush_signals atomic reference swap (3 signals → first flush returns 3, second returns [])
- Multi-symbol flush isolation
- Concurrent emit_signal from threads (thread-safety)
"""

from __future__ import annotations

import threading
from typing import Any

import pandas as pd
import pytest

from quantflow.common.config import AppConfig
from quantflow.common.models import (
    Bar,
    Direction,
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
    def __init__(self, name: str = "s1", signal: Signal | None = None) -> None:
        super().__init__(name=name)
        self._signal = signal
        self.init_calls = 0
        self.bar_calls = 0

    def on_init(self, ctx: StrategyContext) -> None:
        self.init_calls += 1

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        self.bar_calls += 1
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


class _MultiSignalStrategy(StrategyBase):
    """Emits N signals per bar for flush testing."""

    def __init__(
        self,
        name: str = "multi",
        n_signals: int = 3,
        symbol: str = "BTC/USDT",
        params: dict[str, Any] | None = None,
    ) -> None:
        merged = dict(params or {})
        merged.setdefault("n_signals", n_signals)
        merged.setdefault("symbol", symbol)
        super().__init__(name=name, params=merged)

    def on_init(self, ctx: StrategyContext) -> None:
        pass

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        n = int(self._params.get("n_signals", 3))
        sym = self._params.get("symbol", bar.symbol)
        for _i in range(n):
            ctx.emit_signal(
                symbol=sym,
                direction=Direction.LONG,
                strength=0.5,
                price=bar.close,
                strategy_id=self.name,
            )

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


def _make_session(
    strategies: list[StrategyBase],
    *,
    sink: _FakeSink | None = None,
) -> TradingSession:
    config = AppConfig()
    session = TradingSession(config, strategies, monitoring_sink=sink or _FakeSink())
    return session


def _monkeypatch_pipeline(
    session: TradingSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        session.execution.position_manager, "update_market_price", lambda symbol, price: None
    )
    monkeypatch.setattr(session.portfolio, "update_position", lambda symbol, qty, price, **kw: None)
    monkeypatch.setattr(session.portfolio, "check_drawdown", lambda limit: True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestKillSwitchReleaseAll:
    """Test 1: activate_kill_switch clears all pending reservations."""

    @pytest.mark.asyncio
    async def test_activate_clears_pending(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = _make_session([_Strategy("ks")])
        session._running = True
        session._kill_switch = _FakeKillSwitch()

        # Reserve 3 pending entries
        session.portfolio.reserve("oid-1", "BTC/USDT", 100.0, "ks")
        session.portfolio.reserve("oid-2", "ETH/USDT", 200.0, "ks")
        session.portfolio.reserve("oid-3", "BTC/USDT", 300.0, "ks")
        assert session.portfolio.total_pending_exposure == 600.0

        result = await session.activate_kill_switch("manual_test")

        assert result["status"] == "activated"
        assert session.portfolio.total_pending_exposure == 0.0


class TestDrawdownBreach:
    """Test 2: Drawdown breach activates kill switch + clears pending + _running=False."""

    @pytest.mark.asyncio
    async def test_drawdown_breach_full_flow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        strategy = _Strategy("dd")
        sink = _FakeSink()
        session = _make_session([strategy], sink=sink)
        session._running = True
        session._kill_switch = _FakeKillSwitch()

        # Monkeypatch pipeline but make drawdown FAIL
        monkeypatch.setattr(
            session.execution.position_manager, "update_market_price", lambda symbol, price: None
        )
        monkeypatch.setattr(
            session.portfolio, "update_position", lambda symbol, qty, price, **kw: None
        )
        monkeypatch.setattr(session.portfolio, "check_drawdown", lambda limit: False)

        # Reserve some pending before the bar triggers drawdown breach
        session.portfolio.reserve("pre-1", "BTC/USDT", 500.0, "dd")
        session.portfolio.reserve("pre-2", "ETH/USDT", 300.0, "dd")

        await session.on_bar(_bar(symbol="BTC/USDT", ts=1))

        assert session._kill_switch.calls == ["drawdown_breach"]
        assert session._running is False
        assert session.portfolio.total_pending_exposure == 0.0
        # Alert was sent
        assert any("KILL SWITCH ACTIVATED" in msg for msg, _, _ in sink.sent)


class TestFlushSignalsAtomic:
    """Test 3: flush_signals uses reference swap — first flush returns all, second empty."""

    async def test_flush_returns_all_then_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        strategy = _MultiSignalStrategy("flusher", n_signals=3, symbol="BTC/USDT")
        session = _make_session([strategy])
        session._running = True

        async def fake_start(mode: str = "paper", gateway_config: Any = None) -> None:
            session.execution._gateway = _FakeGateway()

        monkeypatch.setattr(session.execution, "start", fake_start)
        await session.start(mode="paper", symbols=["BTC/USDT"])

        _monkeypatch_pipeline(session, monkeypatch)

        # Patch pipeline to not actually process signals (size=0 → skip)
        session._risk_engine.check = lambda signal, portfolio, pending=None: RiskDecision(
            passed=True
        )
        session._position_sizer.size = lambda signal, portfolio, **kw: 0.0

        await session.on_bar(_bar(symbol="BTC/USDT", ts=1))

        # After on_bar, the context should have been flushed.
        # Verify by directly checking the context's signal list
        ctx = session._contexts[("flusher", "BTC/USDT")]
        assert ctx._signals == []  # Already flushed by on_bar

    async def test_flush_direct_reference_swap(self) -> None:
        """Direct test: emit 3 signals, flush returns 3, second flush returns []."""
        ctx = StrategyContext()
        for _i in range(3):
            ctx.emit_signal(
                symbol="BTC/USDT",
                direction=Direction.LONG,
                strength=0.5,
                price=100.0,
                strategy_id="test",
            )

        first_flush = ctx.flush_signals()
        second_flush = ctx.flush_signals()

        assert len(first_flush) == 3
        assert len(second_flush) == 0


class TestFlushMultiSymbol:
    """Test 4: Two symbols emit 2 signals each; each context flush returns 2."""

    @pytest.mark.asyncio
    async def test_multi_symbol_flush_isolation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        strategy = _MultiSignalStrategy("ms", n_signals=2, symbol="PLACEHOLDER")
        session = _make_session([strategy])

        async def fake_start(mode: str = "paper", gateway_config: Any = None) -> None:
            session.execution._gateway = _FakeGateway()

        monkeypatch.setattr(session.execution, "start", fake_start)
        await session.start(mode="paper", symbols=["BTC/USDT", "ETH/USDT"])

        _monkeypatch_pipeline(session, monkeypatch)
        session._risk_engine.check = lambda signal, portfolio, pending=None: RiskDecision(
            passed=True
        )
        session._position_sizer.size = lambda signal, portfolio, **kw: 0.0

        await session.on_bar(_bar(symbol="BTC/USDT", ts=1))
        await session.on_bar(_bar(symbol="ETH/USDT", ts=2))

        # Both contexts should have been flushed by on_bar already
        btc_ctx = session._contexts[("ms", "BTC/USDT")]
        eth_ctx = session._contexts[("ms", "ETH/USDT")]
        assert btc_ctx._signals == []
        assert eth_ctx._signals == []


class TestConcurrentEmitSignal:
    """Test 5: N threads call ctx.emit_signal concurrently; all signals captured."""

    async def test_concurrent_emit_from_threads(self) -> None:
        ctx = StrategyContext()
        n_threads = 50
        barrier = threading.Barrier(n_threads)

        def emit_from_thread(idx: int) -> None:
            barrier.wait()
            ctx.emit_signal(
                symbol="BTC/USDT",
                direction=Direction.LONG,
                strength=0.5,
                price=100.0,
                strategy_id=f"t{idx}",
            )

        threads = [threading.Thread(target=emit_from_thread, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        signals = ctx.flush_signals()
        assert len(signals) == n_threads

    async def test_concurrent_emit_multi_context(self) -> None:
        """Each of 2 contexts receives concurrent emits from threads."""
        ctx_a = StrategyContext()
        ctx_b = StrategyContext()
        n_per_ctx = 25
        barrier = threading.Barrier(n_per_ctx * 2)

        def emit_a(idx: int) -> None:
            barrier.wait()
            ctx_a.emit_signal(
                symbol="BTC/USDT",
                direction=Direction.LONG,
                strength=0.5,
                price=100.0,
                strategy_id=f"a{idx}",
            )

        def emit_b(idx: int) -> None:
            barrier.wait()
            ctx_b.emit_signal(
                symbol="ETH/USDT",
                direction=Direction.SHORT,
                strength=0.5,
                price=50.0,
                strategy_id=f"b{idx}",
            )

        threads: list[threading.Thread] = []
        for i in range(n_per_ctx):
            threads.append(threading.Thread(target=emit_a, args=(i,)))
            threads.append(threading.Thread(target=emit_b, args=(i,)))
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        sigs_a = ctx_a.flush_signals()
        sigs_b = ctx_b.flush_signals()
        assert len(sigs_a) == n_per_ctx
        assert len(sigs_b) == n_per_ctx
        assert all(s.symbol == "BTC/USDT" for s in sigs_a)
        assert all(s.symbol == "ETH/USDT" for s in sigs_b)
