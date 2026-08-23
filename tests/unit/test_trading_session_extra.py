"""Additional branch coverage tests for TradingSession."""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
import pytest

from quantflow.common.config import AlertChannelConfig, AppConfig, MonitoringConfig
from quantflow.common.event_bus import EVENT_RISK, Event
from quantflow.common.models import (
    Bar,
    Direction,
    Order,
    OrderRequest,
    OrderSide,
    OrderStatus,
    RiskDecision,
    Signal,
)
from quantflow.execution.gateway_base import GatewayBase
from quantflow.strategy.base import StrategyBase, StrategyContext
from quantflow.strategy.engine import TradingSession


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


class _FakeAlertManager:
    """Deprecated: tests now inject _FakeSink directly (ISS-019). Kept only for
    callers that still reference it via module state; the sink path is canonical."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, object, object]] = []

    async def send(self, message: str, level: object, extra: object = None) -> dict[str, bool]:
        self.sent.append((message, level, extra))
        return {"ok": True}


class _FakeSink:
    """Recording MonitoringSink for tests (ISS-019): replaces both the patched
    module-level metrics functions and the AlertManager. send_alert args are
    captured in ``sent`` as (message, level, extra); record_* calls are captured
    in the matching lists."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, object]] = []
        self.portfolio_updates: list[dict[str, float | int]] = []
        self.signals: list[tuple[str, str]] = []
        self.bar_observations: list[tuple[str, float]] = []
        self.signal_observations: list[tuple[str, float]] = []
        # ISS-20260724-044 (ISS-019) + ISS-20260723-011 (OBS-M): recorders for
        # every sink method so the full Protocol surface is captured.
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
        self,
        total_value: float,
        cash: float,
        drawdown: float,
        n_positions: int,
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
        self,
        message: str,
        level: str = "warning",
        extra: dict[str, object] | None = None,
    ) -> dict[str, bool]:
        self.sent.append((message, level, extra))
        return {"ok": True}


def _bar(price: float = 100.0, ts: int = 1) -> Bar:
    return Bar(
        symbol="BTC/USDT",
        timestamp=ts,
        open=price - 1,
        high=price + 1,
        low=price - 2,
        close=price,
        volume=10.0,
    )


class TestTradingSessionExtra:
    @pytest.mark.asyncio
    async def test_start_initializes_kill_switch_alert_manager_and_allocations(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = AppConfig(
            monitoring=MonitoringConfig(
                alert_channels=[AlertChannelConfig(chat_id="chat", token="token")]
            )
        )
        strategies = [_Strategy("alpha"), _Strategy("beta")]
        sink = _FakeSink()
        session = TradingSession(config, strategies, monitoring_sink=sink)

        async def fake_start(mode: str = "paper", gateway_config=None) -> None:
            session.execution._gateway = _FakeGateway()

        monkeypatch.setattr(session.execution, "start", fake_start)
        allocation_calls: list[dict[str, float]] = []
        original_set_allocation = session.portfolio.set_allocation

        def track_set_allocation(allocation: dict[str, float]) -> None:
            allocation_calls.append(dict(allocation))
            original_set_allocation(allocation)

        monkeypatch.setattr(session.portfolio, "set_allocation", track_set_allocation)

        await session.start(mode="paper")

        assert session.kill_switch is not None
        # ISS-019: sink.start() ran (no metrics-server crash); the alert channel
        # is now wired inside the sink, not as session._alert_mgr.
        assert session._sink is sink
        assert strategies[0].init_calls == 1
        assert strategies[1].init_calls == 1
        assert session.portfolio.get_strategy_allocation("alpha") == 0.5
        assert session.portfolio.get_strategy_allocation("beta") == 0.5
        assert allocation_calls == [{"alpha": 0.5, "beta": 0.5}]

    @pytest.mark.asyncio
    async def test_start_only_attempts_metrics_server_once_per_port(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ISS-019: per-port idempotency now lives in metrics.start_metrics_server
        # (called via DefaultMonitoringSink.start). Two sessions on the same port
        # must start the HTTP server exactly once.
        from quantflow.monitoring import metrics
        from quantflow.monitoring.sink import create_default_sink

        port = AppConfig().monitoring.prometheus_port
        metrics._METRICS_SERVER_STATE.pop(port, None)

        calls: list[int] = []
        monkeypatch.setattr(
            "quantflow.monitoring.metrics.start_http_server", lambda p: calls.append(p)
        )

        first = TradingSession(
            AppConfig(), [_Strategy("alpha")], monitoring_sink=create_default_sink()
        )
        second = TradingSession(
            AppConfig(), [_Strategy("alpha")], monitoring_sink=create_default_sink()
        )

        async def fake_start(mode: str = "paper", gateway_config=None) -> None:
            return None

        monkeypatch.setattr(first.execution, "start", fake_start)
        monkeypatch.setattr(second.execution, "start", fake_start)

        await first.start(mode="paper")
        await second.start(mode="paper")

        assert calls == [port]

    @pytest.mark.asyncio
    async def test_on_bar_returns_early_when_not_running_or_kill_switch_active(self) -> None:
        signal = Signal(
            symbol="BTC/USDT",
            direction=Direction.LONG,
            strength=0.8,
            price=100.0,
            strategy_id="s1",
        )
        strategy = _Strategy(signal=signal)
        session = TradingSession(AppConfig(), [strategy])

        await session.on_bar(_bar())
        assert strategy.bar_calls == 0

        session._running = True
        session._kill_switch = _FakeKillSwitch(active=True)
        await session.on_bar(_bar())
        assert strategy.bar_calls == 0

    @pytest.mark.asyncio
    async def test_on_bar_drawdown_breach_activates_kill_switch_and_alerts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = TradingSession(AppConfig(), [_Strategy()])
        session._running = True
        session._kill_switch = _FakeKillSwitch()
        sink = _FakeSink()
        session._sink = sink

        monkeypatch.setattr(
            session.execution.position_manager, "update_market_price", lambda symbol, price: None
        )
        monkeypatch.setattr(session.portfolio, "update_position", lambda symbol, qty, price: None)
        monkeypatch.setattr(session.portfolio, "check_drawdown", lambda limit: False)

        await session.on_bar(_bar())

        assert session.kill_switch.calls == ["drawdown_breach"]
        assert session._running is False
        assert sink.sent[0][0] == "KILL SWITCH ACTIVATED: drawdown breach"

    @pytest.mark.asyncio
    async def test_on_bar_skips_strategy_when_context_is_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        strategy = _Strategy("ghost")
        session = TradingSession(AppConfig(), [strategy])
        session._running = True
        session._contexts = {}

        monkeypatch.setattr(
            session.execution.position_manager, "update_market_price", lambda symbol, price: None
        )
        monkeypatch.setattr(session.portfolio, "update_position", lambda symbol, qty, price: None)
        monkeypatch.setattr(session.portfolio, "check_drawdown", lambda limit: True)

        await session.on_bar(_bar())

        assert strategy.bar_calls == 0

    @pytest.mark.asyncio
    async def test_process_signal_blocks_on_risk_and_sends_alert(self) -> None:
        session = TradingSession(AppConfig(), [_Strategy()])
        session._running = True
        sink = _FakeSink()
        session._sink = sink
        events: list[str] = []
        session._event_bus.subscribe(EVENT_RISK, lambda e: events.append(e.data["reason"]))
        session._risk_engine.check = lambda signal, portfolio, pending=None: RiskDecision(
            passed=False, reason="max_drawdown"
        )

        signal = Signal(
            symbol="BTC/USDT",
            direction=Direction.LONG,
            strength=0.9,
            price=100.0,
            strategy_id="risky",
        )
        await session._process_signal(signal)

        assert events == ["max_drawdown"]
        assert sink.sent[0][0] == "Signal blocked: max_drawdown"

    @pytest.mark.asyncio
    async def test_process_signal_skips_zero_size_and_submits_long_and_short_orders(self) -> None:
        strategy = _Strategy()
        session = TradingSession(AppConfig(), [strategy])
        session._running = True
        session.portfolio.set_allocation({"zero": 1.0, "long": 0.5, "short": 1.0})
        session._risk_engine.check = lambda signal, portfolio, pending=None: RiskDecision(
            passed=True
        )

        submitted: list[tuple[str, str, float]] = []

        async def fake_submit_order(request: OrderRequest) -> Order:
            submitted.append((request.strategy_id, request.side.value, request.quantity))
            return Order(
                order_id="submitted",
                symbol=request.symbol,
                side=request.side,
                order_type=request.order_type,
                quantity=request.quantity,
                price=request.price,
                status=OrderStatus.SUBMITTED,
                strategy_id=request.strategy_id,
            )

        session.execution.submit_order = fake_submit_order

        # ISS-038: allocation is now passed INTO size() (not multiplied
        # externally), so quantity = size / price. The mock ignores allocation
        # (allocation semantics are pinned in test_position_sizer.py); this
        # test focuses on _process_signal's submit + quantity conversion.
        size_iter = iter([0.0, 20.0, 15.0])
        session._position_sizer.size = lambda signal, portfolio, **kw: next(size_iter)

        await session._process_signal(
            Signal("BTC/USDT", Direction.LONG, strength=0.5, price=100.0, strategy_id="zero")
        )
        await session._process_signal(
            Signal("BTC/USDT", Direction.LONG, strength=0.5, price=100.0, strategy_id="long")
        )
        await session._process_signal(
            Signal("BTC/USDT", Direction.SHORT, strength=0.5, price=50.0, strategy_id="short")
        )

        assert submitted == [
            ("long", "buy", 0.2),
            ("short", "sell", 0.3),
        ]

    @pytest.mark.asyncio
    async def test_process_signal_syncs_portfolio_and_metrics_on_fill(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = TradingSession(AppConfig(), [_Strategy()])
        session._running = True
        session.portfolio.set_allocation({"filled": 1.0})
        session._risk_engine.check = lambda signal, portfolio, pending=None: RiskDecision(
            passed=True
        )
        session._position_sizer.size = lambda signal, portfolio, **kw: 25.0
        sink = _FakeSink()
        session._sink = sink

        async def fake_submit_order(request: OrderRequest) -> Order:
            order = Order(
                order_id="filled-1",
                symbol=request.symbol,
                side=request.side,
                order_type=request.order_type,
                quantity=request.quantity,
                price=request.price,
                status=OrderStatus.FILLED,
                filled_quantity=request.quantity,
                filled_price=110.0,
                fee=2.5,
                strategy_id=request.strategy_id,
            )
            # ISS-20260720-004 Wave 2: L4 fill update is owned by
            # ExecutionEngine.submit. This mock replaces submit_order wholesale,
            # so it must mirror that single L4 update (fee included) — otherwise
            # the signal path's observability read sees a stale book.
            signed = request.quantity if request.side == OrderSide.BUY else -request.quantity
            session.portfolio.update_position(
                order.symbol,
                signed,
                110.0,
                fee=order.fee,
                strategy_id=order.strategy_id,
            )
            return order

        session.execution.submit_order = fake_submit_order

        await session._process_signal(
            Signal("BTC/USDT", Direction.LONG, strength=0.5, price=100.0, strategy_id="filled")
        )

        position = session.portfolio.get_position("BTC/USDT")
        assert position is not None
        assert position.quantity == pytest.approx(0.25)
        assert position.entry_price == pytest.approx(110.0)
        assert session.portfolio.cash == pytest.approx(99970.0)
        assert sink.portfolio_updates[-1]["cash"] == pytest.approx(99970.0)
        assert sink.portfolio_updates[-1]["total_value"] == pytest.approx(99997.5)
        assert sink.portfolio_updates[-1]["n_positions"] == 1

    @pytest.mark.asyncio
    async def test_on_bar_records_bar_and_signal_latency_metrics(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        signal = Signal(
            symbol="BTC/USDT",
            direction=Direction.LONG,
            strength=0.5,
            price=100.0,
            strategy_id="latency",
        )
        strategy = _Strategy("latency", signal=signal)
        sink = _FakeSink()
        session = TradingSession(AppConfig(), [strategy], monitoring_sink=sink)
        session._running = True
        session._contexts = {("latency", ""): StrategyContext()}
        session.portfolio.set_allocation({"latency": 1.0})
        session._risk_engine.check = lambda signal, portfolio, pending=None: RiskDecision(
            passed=True
        )
        session._position_sizer.size = lambda signal, portfolio, **kw: 0.0

        monkeypatch.setattr(
            session.execution.position_manager, "update_market_price", lambda symbol, price: None
        )
        monkeypatch.setattr(session.portfolio, "update_position", lambda symbol, qty, price: None)
        monkeypatch.setattr(session.portfolio, "check_drawdown", lambda limit: True)

        await session.on_bar(_bar())

        # ISS-019: latency now flows through the sink, not module-level histograms.
        assert any(symbol == "BTC/USDT" for symbol, _ in sink.bar_observations)
        assert any(sid == "latency" for sid, _ in sink.signal_observations)
        assert all(value >= 0 for _, value in sink.bar_observations)
        assert all(value >= 0 for _, value in sink.signal_observations)

    def test_on_risk_event_and_check_health_cover_remaining_branches(self) -> None:
        session = TradingSession(AppConfig(), [_Strategy()])
        session._kill_switch = _FakeKillSwitch(active=False)

        # DEF-REV011-B: emergency arms the kill switch via a fire-and-forget
        # task; run inside a loop and drain before asserting side effects.
        import asyncio as _aio

        async def _fire():
            session._on_risk_event(Event(EVENT_RISK, {"severity": "emergency"}))
            pending = [t for t in session._background_tasks if not t.done()]
            if pending:
                await _aio.gather(*pending, return_exceptions=True)

        _aio.run(_fire())
        assert session.kill_switch is not None and session.kill_switch.calls
        session._on_risk_event(Event(EVENT_RISK, {"severity": "warn"}))

        session._running = True
        # Position lives in the L4 PortfolioManager (authoritative book; check_health
        # reads open_positions from L4, not L5 — ISS-20260720-004 unification).
        # A real fill goes through _process_signal → portfolio.update_position; this
        # stub mirrors that by writing to L4 directly.
        session.portfolio.update_position("BTC/USDT", 1.0, 100.0)
        session.execution.order_manager.track(
            OrderRequest(
                symbol="BTC/USDT",
                side=OrderSide.BUY,
                order_type="market",
                quantity=1.0,
                price=100.0,
                strategy_id="x",
            ),
            None,
        )
        session.portfolio._current_drawdown = -0.2

        health = session.check_health()

        assert health["running"] is True
        assert health["drawdown_ok"] is False
        assert health["pending_orders"] == 1
        assert health["open_positions"] == 1

    @pytest.mark.asyncio
    async def test_run_data_loop_processes_new_bars_and_handles_fetch_errors(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = TradingSession(AppConfig(), [_Strategy()])
        session._running = True
        session._config.execution.mode = "live"
        seen: list[int] = []
        timeout_checks: list[str] = []
        health_checks: list[str] = []

        async def fake_on_bar(bar: Bar) -> None:
            seen.append(bar.timestamp)

        def fake_check_health() -> dict[str, bool]:
            health_checks.append("ok")
            return {"running": True}

        def fake_check_timeouts() -> list[str]:
            timeout_checks.append("tick")
            return []

        session.on_bar = fake_on_bar
        session.check_health = fake_check_health
        session.execution.check_timeouts = fake_check_timeouts

        class FakeFetcher:
            def __init__(self, config: object) -> None:
                self.calls = 0
                self.disconnected = False

            async def connect(self) -> None:
                return None

            async def fetch_ohlcv(
                self, symbol: str, timeframe: str, start: object = None, limit: int = 10
            ) -> pd.DataFrame:
                self.calls += 1
                if self.calls == 1:
                    return pd.DataFrame(
                        [
                            {
                                "timestamp": 1,
                                "open": 99.0,
                                "high": 101.0,
                                "low": 98.0,
                                "close": 100.0,
                                "volume": 10.0,
                            },
                            {
                                "timestamp": 1,
                                "open": 99.0,
                                "high": 101.0,
                                "low": 98.0,
                                "close": 100.0,
                                "volume": 10.0,
                            },
                            {
                                "timestamp": 2,
                                "open": 100.0,
                                "high": 102.0,
                                "low": 99.0,
                                "close": 101.0,
                                "volume": 11.0,
                            },
                        ]
                    )
                if self.calls == 2:
                    raise RuntimeError("feed error")
                session._running = False
                return pd.DataFrame()

            async def disconnect(self) -> None:
                self.disconnected = True

        fetcher_holder: dict[str, FakeFetcher] = {}

        def fake_fetcher_factory(config: object) -> FakeFetcher:
            fetcher_holder["fetcher"] = FakeFetcher(config)
            return fetcher_holder["fetcher"]

        async def fake_sleep(seconds: int) -> None:
            return None

        monkeypatch.setattr("quantflow.data.fetcher.DataFetcher", fake_fetcher_factory)
        monkeypatch.setattr("quantflow.strategy.engine.asyncio.sleep", fake_sleep)

        await session.run_data_loop("BTC/USDT", interval_seconds=0)

        assert seen == [1, 2]
        assert health_checks == ["ok", "ok", "ok"]
        assert timeout_checks == ["tick", "tick", "tick"]
        assert fetcher_holder["fetcher"].disconnected is True

    @pytest.mark.asyncio
    async def test_run_data_loop_handles_cancellation_and_stop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = TradingSession(AppConfig(), [_Strategy()])
        session._running = True
        session._config.execution.mode = "live"
        stopped: list[str] = []

        class FakeFetcher:
            async def connect(self) -> None:
                return None

            async def fetch_ohlcv(
                self, symbol: str, timeframe: str, start: object = None, limit: int = 10
            ) -> pd.DataFrame:
                return pd.DataFrame()

            async def disconnect(self) -> None:
                stopped.append("disconnected")

        monkeypatch.setattr("quantflow.data.fetcher.DataFetcher", lambda config: FakeFetcher())
        session.check_health = lambda: {"running": True}
        session.execution.check_timeouts = lambda: []

        async def fake_sleep(seconds: int) -> None:
            raise asyncio.CancelledError()

        monkeypatch.setattr("quantflow.strategy.engine.asyncio.sleep", fake_sleep)

        await session.run_data_loop("BTC/USDT", interval_seconds=0)

        assert stopped == ["disconnected"]

        async def fake_stop() -> None:
            stopped.append("stopped")

        session.execution.stop = fake_stop
        await session.stop()
        assert session._running is False
        assert stopped[-1] == "stopped"

    @pytest.mark.asyncio
    async def test_run_data_loop_retries_connect_until_data_feed_recovers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = TradingSession(AppConfig(), [_Strategy()])
        session._running = True
        session._config.execution.mode = "live"
        seen: list[int] = []
        health_checks: list[str] = []
        timeout_checks: list[str] = []

        async def fake_on_bar(bar: Bar) -> None:
            seen.append(bar.timestamp)

        session.on_bar = fake_on_bar

        def fake_check_health() -> dict[str, bool]:
            health_checks.append("ok")
            return {"running": True}

        def fake_check_timeouts() -> list[str]:
            timeout_checks.append("tick")
            return []

        session.check_health = fake_check_health
        session.execution.check_timeouts = fake_check_timeouts

        class FakeFetcher:
            def __init__(self, config: object) -> None:
                self.connect_calls = 0
                self.fetch_calls = 0
                self.disconnect_calls = 0

            async def connect(self) -> None:
                self.connect_calls += 1
                if self.connect_calls == 1:
                    raise RuntimeError("connect down")

            async def fetch_ohlcv(
                self, symbol: str, timeframe: str, start: object = None, limit: int = 10
            ) -> pd.DataFrame:
                self.fetch_calls += 1
                session._running = False
                return pd.DataFrame(
                    [
                        {
                            "timestamp": 10,
                            "open": 100.0,
                            "high": 101.0,
                            "low": 99.0,
                            "close": 100.5,
                            "volume": 5.0,
                        }
                    ]
                )

            async def disconnect(self) -> None:
                self.disconnect_calls += 1

        fetcher_holder: dict[str, FakeFetcher] = {}

        def fake_fetcher_factory(config: object) -> FakeFetcher:
            fetcher_holder["fetcher"] = FakeFetcher(config)
            return fetcher_holder["fetcher"]

        async def fake_sleep(seconds: int) -> None:
            return None

        monkeypatch.setattr("quantflow.data.fetcher.DataFetcher", fake_fetcher_factory)
        monkeypatch.setattr("quantflow.strategy.engine.asyncio.sleep", fake_sleep)

        await session.run_data_loop("BTC/USDT", interval_seconds=0)

        fetcher = fetcher_holder["fetcher"]
        assert fetcher.connect_calls == 2
        assert fetcher.fetch_calls == 1
        assert fetcher.disconnect_calls == 2
        assert seen == [10]
        assert health_checks == ["ok", "ok"]
        assert timeout_checks == ["tick", "tick"]

    @pytest.mark.asyncio
    async def test_run_data_loop_prefers_local_parquet_replay_for_paper_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = TradingSession(AppConfig(), [_Strategy()])
        session._running = True
        session._config.execution.mode = "paper"
        seen: list[int] = []
        timeout_checks: list[str] = []
        health_checks: list[str] = []

        async def fake_on_bar(bar: Bar) -> None:
            seen.append(bar.timestamp)
            if bar.timestamp >= 2:
                session._running = False

        def fake_check_health() -> dict[str, bool]:
            health_checks.append("ok")
            return {"running": session._running}

        def fake_check_timeouts() -> list[str]:
            timeout_checks.append("tick")
            return []

        session.on_bar = fake_on_bar
        session.check_health = fake_check_health
        session.execution.check_timeouts = fake_check_timeouts

        class FakeStore:
            def __init__(self, parquet_dir: str, duckdb_path: str) -> None:
                assert duckdb_path == ":memory:"
                self.calls = 0
                self.closed = False

            def query(
                self,
                symbol: str,
                start: int | None = None,
                end: int | None = None,
                timeframe: str | None = None,
                columns=None,
            ) -> pd.DataFrame:
                self.calls += 1
                if self.calls == 1:
                    assert timeframe == "1h"
                    return pd.DataFrame()
                if self.calls == 2:
                    return pd.DataFrame(
                        [
                            {
                                "timestamp": 1,
                                "open": 99.0,
                                "high": 101.0,
                                "low": 98.0,
                                "close": 100.0,
                                "volume": 10.0,
                                "timeframe": "1d",
                            },
                            {
                                "timestamp": 2,
                                "open": 100.0,
                                "high": 102.0,
                                "low": 99.0,
                                "close": 101.0,
                                "volume": 11.0,
                                "timeframe": "1d",
                            },
                        ]
                    )
                assert timeframe is None
                assert start == 3
                return pd.DataFrame()

            def resolve_symbol(self, symbol: str, **k) -> str:  # REV-026 parity
                return symbol

            def close(self) -> None:
                self.closed = True

        def fail_fetcher_factory(config: object) -> object:
            raise AssertionError("paper local replay should not instantiate DataFetcher")

        store_holder: dict[str, FakeStore] = {}

        def fake_store_factory(parquet_dir: str, duckdb_path: str) -> FakeStore:
            store_holder["store"] = FakeStore(parquet_dir, duckdb_path)
            return store_holder["store"]

        async def fake_sleep(seconds: int) -> None:
            return None

        monkeypatch.setattr("quantflow.data.store.DataStore", fake_store_factory)
        monkeypatch.setattr("quantflow.data.fetcher.DataFetcher", fail_fetcher_factory)
        monkeypatch.setattr("quantflow.strategy.engine.asyncio.sleep", fake_sleep)

        await session.run_data_loop("BTC/USDT", timeframe="1h", interval_seconds=0)

        assert seen == [1, 2]
        assert health_checks == ["ok"]
        assert timeout_checks == ["tick"]
        assert session.last_error is None
        assert store_holder["store"].closed is True
