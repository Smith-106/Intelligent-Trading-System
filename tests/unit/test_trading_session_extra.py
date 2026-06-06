"""Additional branch coverage tests for TradingSession."""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
import pytest

from quantflow.common.config import AlertChannelConfig, AppConfig, MonitoringConfig
from quantflow.common.event_bus import EVENT_RISK, Event
from quantflow.common.models import Bar, Direction, OrderRequest, OrderSide, RiskDecision, Signal
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


class _FakeKillSwitch:
    def __init__(self, active: bool = False) -> None:
        self.is_active = active
        self.calls: list[str] = []

    async def activate(self, reason: str) -> dict[str, str]:
        self.calls.append(reason)
        self.is_active = True
        return {"status": "activated"}


class _FakeAlertManager:
    def __init__(self) -> None:
        self.sent: list[tuple[str, object, object]] = []

    async def send(self, message: str, level: object, extra: object = None) -> dict[str, bool]:
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
        session = TradingSession(config, strategies)

        async def fake_start(mode: str = "paper", gateway_config=None) -> None:
            session.execution._gateway = _FakeGateway()

        monkeypatch.setattr(session.execution, "start", fake_start)
        monkeypatch.setattr("quantflow.strategy.engine.start_metrics_server", lambda port: None)

        await session.start(mode="paper")

        assert session.kill_switch is not None
        assert session._alert_mgr is not None
        assert strategies[0].init_calls == 1
        assert strategies[1].init_calls == 1
        assert session.portfolio.get_strategy_allocation("alpha") == 0.5
        assert session.portfolio.get_strategy_allocation("beta") == 0.5

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
        session._alert_mgr = _FakeAlertManager()

        monkeypatch.setattr(
            session.execution.position_manager, "update_market_price", lambda symbol, price: None
        )
        monkeypatch.setattr(session.portfolio, "update_position", lambda symbol, qty, price: None)
        monkeypatch.setattr(
            "quantflow.strategy.engine.update_portfolio_metrics", lambda **kwargs: None
        )
        monkeypatch.setattr(session.portfolio, "check_drawdown", lambda limit: False)

        await session.on_bar(_bar())

        assert session.kill_switch.calls == ["drawdown_breach"]
        assert session._running is False
        assert session._alert_mgr.sent[0][0] == "KILL SWITCH ACTIVATED: drawdown breach"

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
        monkeypatch.setattr(
            "quantflow.strategy.engine.update_portfolio_metrics", lambda **kwargs: None
        )
        monkeypatch.setattr(session.portfolio, "check_drawdown", lambda limit: True)

        await session.on_bar(_bar())

        assert strategy.bar_calls == 0

    @pytest.mark.asyncio
    async def test_process_signal_blocks_on_risk_and_sends_alert(self) -> None:
        session = TradingSession(AppConfig(), [_Strategy()])
        session._running = True
        session._alert_mgr = _FakeAlertManager()
        events: list[str] = []
        session._event_bus.subscribe(EVENT_RISK, lambda e: events.append(e.data["reason"]))
        session._risk_engine.check = lambda signal, portfolio: RiskDecision(
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
        assert session._alert_mgr.sent[0][0] == "Signal blocked: max_drawdown"

    @pytest.mark.asyncio
    async def test_process_signal_skips_zero_size_and_submits_long_and_short_orders(self) -> None:
        strategy = _Strategy()
        session = TradingSession(AppConfig(), [strategy])
        session._running = True
        session.portfolio.set_allocation({"zero": 1.0, "long": 0.5, "short": 1.0})
        session._risk_engine.check = lambda signal, portfolio: RiskDecision(passed=True)

        submitted: list[tuple[str, str, float]] = []

        async def fake_submit_order(request: OrderRequest) -> object:
            submitted.append((request.strategy_id, request.side.value, request.quantity))
            return object()

        session.execution.submit_order = fake_submit_order

        size_iter = iter([0.0, 20.0, 15.0])
        session._position_sizer.size = lambda signal, portfolio: next(size_iter)

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
            ("long", "buy", 0.1),
            ("short", "sell", 0.3),
        ]

    @pytest.mark.asyncio
    async def test_on_bar_records_bar_and_signal_latency_metrics(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        observations: list[tuple[dict[str, str], float]] = []

        class FakeHistogram:
            def labels(self, **labels: str) -> object:
                class Child:
                    def observe(self, value: float) -> None:
                        observations.append((labels, value))

                return Child()

        signal = Signal(
            symbol="BTC/USDT",
            direction=Direction.LONG,
            strength=0.5,
            price=100.0,
            strategy_id="latency",
        )
        strategy = _Strategy("latency", signal=signal)
        session = TradingSession(AppConfig(), [strategy])
        session._running = True
        session._contexts = {"latency": StrategyContext()}
        session.portfolio.set_allocation({"latency": 1.0})
        session._risk_engine.check = lambda signal, portfolio: RiskDecision(passed=True)
        session._position_sizer.size = lambda signal, portfolio: 0.0

        monkeypatch.setattr(
            session.execution.position_manager, "update_market_price", lambda symbol, price: None
        )
        monkeypatch.setattr(session.portfolio, "update_position", lambda symbol, qty, price: None)
        monkeypatch.setattr(
            "quantflow.strategy.engine.update_portfolio_metrics", lambda **kwargs: None
        )
        monkeypatch.setattr(session.portfolio, "check_drawdown", lambda limit: True)
        monkeypatch.setattr("quantflow.strategy.engine.BAR_PROCESSING_LATENCY", FakeHistogram())
        monkeypatch.setattr(
            "quantflow.strategy.engine.SIGNAL_PROCESSING_LATENCY", FakeHistogram()
        )

        await session.on_bar(_bar())

        assert any(labels == {"symbol": "BTC/USDT"} for labels, _ in observations)
        assert any(labels == {"strategy_id": "latency"} for labels, _ in observations)
        assert all(value >= 0 for _, value in observations)

    def test_on_risk_event_and_check_health_cover_remaining_branches(self) -> None:
        session = TradingSession(AppConfig(), [_Strategy()])
        session._kill_switch = _FakeKillSwitch(active=False)
        session._on_risk_event(Event(EVENT_RISK, {"severity": "emergency"}))
        session._on_risk_event(Event(EVENT_RISK, {"severity": "warn"}))

        session._running = True
        session.execution.position_manager.update_position("BTC/USDT", 1.0, 100.0)
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
