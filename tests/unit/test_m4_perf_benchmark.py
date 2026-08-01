"""Phase 6 M4 v0.2 — Performance benchmark guard for TradingSession.on_bar."""

from __future__ import annotations

import time
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
from quantflow.strategy.base import StrategyBase, StrategyContext
from quantflow.strategy.engine import TradingSession

# ---------------------------------------------------------------------------
# Local helpers (copied from test_trading_session_extra.py)
# ---------------------------------------------------------------------------


class _Strategy(StrategyBase):
    """Minimal strategy that counts on_bar calls and optionally emits a signal."""

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


class _AlwaysSignalStrategy(StrategyBase):
    """Strategy that emits exactly one signal per bar (for signal-loss test)."""

    def __init__(self, name: str = "always") -> None:
        super().__init__(name=name)
        self.bar_calls = 0

    def on_init(self, ctx: StrategyContext) -> None:
        pass

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        self.bar_calls += 1
        ctx.emit_signal(
            symbol=bar.symbol,
            direction=Direction.LONG,
            strength=0.5,
            price=bar.close,
            strategy_id=self.name,
        )

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        return pd.Series(False, index=df.index), pd.Series(False, index=df.index)


class _FakeSink:
    """Minimal recording sink for perf tests."""

    def __init__(self) -> None:
        self.signals: list[tuple[str, str]] = []
        self.bar_observations: list[tuple[str, float]] = []

    def start(self, config: object) -> None:
        return

    def record_signal(self, strategy_id: str, direction: str) -> None:
        self.signals.append((strategy_id, direction))

    def record_bar_latency(self, symbol: str, duration_seconds: float) -> None:
        self.bar_observations.append((symbol, duration_seconds))

    def record_signal_latency(self, strategy_id: str, duration_seconds: float) -> None:
        pass

    def record_portfolio(self, *args: Any, **kwargs: Any) -> None:
        pass

    def record_risk_event(self, event_type: str, severity: str) -> None:
        pass

    def record_kill_switch_activation(self, reason: str) -> None:
        pass

    def record_kill_switch_step_failure(self, step: str) -> None:
        pass

    def record_order_total(self, symbol: str, side: str, strategy_id: str) -> None:
        pass

    def record_order_filled(self, symbol: str, side: str, strategy_id: str) -> None:
        pass

    def record_order_latency(self, symbol: str, duration_seconds: float) -> None:
        pass

    def record_gateway_connected(self, exchange: str, connected: bool) -> None:
        pass

    def record_gateway_disconnect(self, exchange: str, reason: str) -> None:
        pass

    def record_gateway_reconnect(self, exchange: str, success: bool) -> None:
        pass

    def record_order_timed_out(self, symbol: str, side: str) -> None:
        pass

    async def send_alert(
        self, message: str, level: str = "warning", extra: dict[str, object] | None = None
    ) -> dict[str, bool]:
        return {"ok": True}


# ---------------------------------------------------------------------------
# Local bar factory
# ---------------------------------------------------------------------------


def _bar(symbol: str = "BTC/USDT", price: float = 100.0, ts: int = 1) -> Bar:
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
# Shared session setup
# ---------------------------------------------------------------------------

N_BARS = 500


def _make_session(
    strategies: list[StrategyBase],
    symbols: list[str] | None = None,
) -> TradingSession:
    """Build a TradingSession with risk/sizing/execution stubbed out."""
    sink = _FakeSink()
    session = TradingSession(AppConfig(), strategies, monitoring_sink=sink)
    session._running = True

    # Stub risk engine — always pass
    session._risk_engine.check = lambda signal, portfolio, pending=None: RiskDecision(passed=True)
    # Stub position sizer — fixed notional so quantity > 0
    session._position_sizer.size = lambda signal, portfolio, **kw: 100.0

    # Stub execution.submit_order — fake FILLED, no real I/O
    async def fake_submit_order(request: OrderRequest) -> Order:
        return Order(
            order_id="fake-filled",
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price if request.price else 100.0,
            status=OrderStatus.FILLED,
            filled_quantity=request.quantity,
            filled_price=100.0,
            fee=0.0,
            strategy_id=request.strategy_id,
        )

    session.execution.submit_order = fake_submit_order

    # Set up per-symbol instances and contexts (M4-2.2)
    if symbols:
        session._symbols = symbols
        for strategy in strategies:
            for sym in symbols:
                key = (strategy.name, sym)
                # Clone via the same class for isolation
                if isinstance(strategy, _AlwaysSignalStrategy):
                    inst = _AlwaysSignalStrategy(strategy.name)
                else:
                    inst = _Strategy(strategy.name, signal=getattr(strategy, "_signal", None))
                session._instances[key] = inst
                session._contexts[key] = StrategyContext()
        session.portfolio.set_allocation({s.name: 1.0 / len(strategies) for s in strategies})
    else:
        # Legacy single-symbol path
        for strategy in strategies:
            key = (strategy.name, "")
            session._contexts[key] = StrategyContext()
        session.portfolio.set_allocation({s.name: 1.0 / len(strategies) for s in strategies})

    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestM4PerfBenchmark:
    """Regression perf guards: on_bar throughput stays within generous budgets."""

    async def test_single_symbol_throughput(self) -> None:
        """1 strategy, 1 symbol, 500 bars — must complete < 5.0s."""
        strategy = _AlwaysSignalStrategy("perf1")
        session = _make_session([strategy], symbols=["BTC/USDT"])

        t0 = time.perf_counter()
        for i in range(N_BARS):
            bar = _bar(symbol="BTC/USDT", price=100.0 + i * 0.01, ts=1_000_000 + i * 60_000)
            await session.on_bar(bar)
        elapsed = time.perf_counter() - t0

        bars_per_sec = N_BARS / elapsed if elapsed > 0 else float("inf")
        print(f"\n[single-symbol] {N_BARS} bars in {elapsed:.3f}s → {bars_per_sec:.0f} bars/sec")
        assert elapsed < 5.0, f"Single-symbol throughput exceeded budget: {elapsed:.3f}s >= 5.0s"

    async def test_two_symbol_throughput(self) -> None:
        """500 bars alternating BTC/USDT and ETH/USDT — must complete < 8.0s."""
        strategy = _AlwaysSignalStrategy("perf2")
        session = _make_session([strategy], symbols=["BTC/USDT", "ETH/USDT"])

        symbols = ["BTC/USDT", "ETH/USDT"]
        t0 = time.perf_counter()
        for i in range(N_BARS):
            sym = symbols[i % 2]
            price = 100.0 + i * 0.01 if sym == "BTC/USDT" else 50.0 + i * 0.01
            bar = _bar(symbol=sym, price=price, ts=1_000_000 + i * 60_000)
            await session.on_bar(bar)
        elapsed = time.perf_counter() - t0

        bars_per_sec = N_BARS / elapsed if elapsed > 0 else float("inf")
        print(f"\n[two-symbol]    {N_BARS} bars in {elapsed:.3f}s → {bars_per_sec:.0f} bars/sec")
        assert elapsed < 8.0, f"Two-symbol throughput exceeded budget: {elapsed:.3f}s >= 8.0s"

    async def test_no_signal_loss(self) -> None:
        """Strategy emits 1 signal/bar; all N signals must be flushed and processed."""
        strategy = _AlwaysSignalStrategy("sigloss")
        session = _make_session([strategy], symbols=["BTC/USDT"])
        sink: _FakeSink = session._sink  # type: ignore[assignment]

        for i in range(N_BARS):
            bar = _bar(symbol="BTC/USDT", price=100.0 + i * 0.01, ts=1_000_000 + i * 60_000)
            await session.on_bar(bar)

        # The strategy's bar_calls must equal N_BARS
        inst = session._instances[("sigloss", "BTC/USDT")]
        assert isinstance(inst, _AlwaysSignalStrategy)
        assert inst.bar_calls == N_BARS, (
            f"Strategy on_bar called {inst.bar_calls} times, expected {N_BARS}"
        )

        # The sink must have recorded N_BARS signals (1 per bar, all flushed)
        total_signals = len(sink.signals)
        assert total_signals == N_BARS, (
            f"Signal loss detected: {total_signals} signals recorded, expected {N_BARS}"
        )
