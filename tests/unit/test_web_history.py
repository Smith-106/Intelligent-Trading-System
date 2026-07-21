from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from quantflow.common.event_bus import Event, EventBus
from quantflow.common.models import EVENT_SIGNAL
from quantflow.web.history import StationHistoryStore
from quantflow.web.session_manager import SessionStartRequest, StationSessionManager


def test_station_history_store_persists_recent_records(tmp_path) -> None:
    store = StationHistoryStore(base_dir=tmp_path / "station_history")

    first_research = store.append_research_run(
        {
            "request": {"strategy": "trend_following", "symbol": "BTC/USDT"},
            "data_source": "demo",
            "result": {
                "total_return": 0.12,
                "sharpe_ratio": 1.8,
                "max_drawdown": -0.04,
                "num_trades": 8,
            },
        }
    )
    second_research = store.append_research_run(
        {
            "request": {"strategy": "mean_reversion", "symbol": "ETH/USDT"},
            "data_source": "market",
            "result": {
                "total_return": 0.04,
                "sharpe_ratio": 0.9,
                "max_drawdown": -0.02,
                "num_trades": 3,
            },
        }
    )
    validation = store.append_validation_run(
        {
            "method": "gate",
            "request": {"strategy": "trend_following", "symbol": "BTC/USDT"},
            "data_source": "demo",
            "result": {"decision": "NO-GO", "reason": "PBO too high"},
            "signals": {"entries": 10, "exits": 12, "bars": 360},
            "summary": {
                "method": "gate",
                "method_label": "Validation Gate",
                "decision": "NO-GO",
                "outcome_label": "NO-GO",
                "outcome_tone": "danger",
                "reason": "PBO too high",
                "entries": 10,
                "exits": 12,
                "bars": 360,
                "primary_metric_label": "CPCV PBO",
                "primary_metric_value": 0.75,
                "primary_metric_format": "number",
            },
        }
    )

    store.append_session_event({"session_id": "session-a", "event_type": "session_started"})
    signal_event = store.append_session_event(
        {"session_id": "session-a", "event_type": "signal", "title": "Signal generated"}
    )
    store.append_session_event({"session_id": "session-b", "event_type": "risk"})
    store.append_session_snapshot({"session_id": "session-a", "running": True})
    latest_snapshot = store.append_session_snapshot({"session_id": "session-a", "running": False})
    store.append_session_snapshot({"session_id": "session-b", "running": False})

    research_items = store.list_research_runs(limit=5)
    assert research_items[0]["record_id"] == second_research["record_id"]
    assert research_items[1]["record_id"] == first_research["record_id"]

    validation_items = store.list_validation_runs(limit=5)
    assert validation_items[0]["record_id"] == validation["record_id"]
    assert validation_items[0]["summary"]["decision"] == "NO-GO"
    assert validation_items[0]["summary"]["outcome_label"] == "NO-GO"
    assert validation_items[0]["summary"]["primary_metric_label"] == "CPCV PBO"

    session_events = store.list_session_events(limit=5, session_id="session-a")
    assert session_events[0]["record_id"] == signal_event["record_id"]
    assert all(item["session_id"] == "session-a" for item in session_events)

    session_snapshots = store.list_session_snapshots(limit=5)
    assert session_snapshots[0]["session_id"] == "session-b"
    assert session_snapshots[1]["record_id"] == latest_snapshot["record_id"]
    assert session_snapshots[1]["running"] is False

    workbench_state = store.save_workbench_state(
        {
            "activePanel": "execution",
            "selectedStrategyId": "trend_following",
            "terminalDraft": {"mode": "paper", "symbol": "BTC/USDT"},
        }
    )
    assert workbench_state["activePanel"] == "execution"
    assert workbench_state["savedAt"]

    loaded_workbench_state = store.load_workbench_state()
    assert loaded_workbench_state is not None
    assert loaded_workbench_state["selectedStrategyId"] == "trend_following"
    assert loaded_workbench_state["terminalDraft"]["symbol"] == "BTC/USDT"


@pytest.mark.asyncio
async def test_station_session_history_downgrades_stale_running_snapshots(tmp_path) -> None:
    store = StationHistoryStore(base_dir=tmp_path / "station_history")
    store.append_session_snapshot(
        {
            "session_id": "session-stale",
            "running": True,
            "health": {"running": True, "open_positions": 0, "pending_orders": 0},
            "dashboard": {"status_label": "Running", "status_tone": "accent"},
            "request": {"mode": "paper", "symbol": "BTC/USDT", "timeframe": "1h"},
        }
    )

    manager = StationSessionManager(history_store=store)
    history = await manager.session_history(limit=5)

    assert history["items"][0]["session_id"] == "session-stale"
    assert history["items"][0]["recorded_running"] is True
    assert history["items"][0]["is_live"] is False
    assert history["items"][0]["running"] is False
    assert history["items"][0]["health"]["running"] is False
    assert history["items"][0]["dashboard"]["status_label"] == "Stopped"
    assert history["items"][0]["dashboard"]["status_tone"] == "muted"


class _FakePortfolio:
    def __init__(self) -> None:
        self.cash = 100000.0
        self._initial_capital = self.cash
        self._peak_equity = 102500.0

    def update_cash(self, delta: float) -> None:
        self.cash += delta

    def set_capital_baseline(self, capital: float) -> None:
        self._initial_capital = capital
        self._peak_equity = max(capital, self._peak_equity)

    def snapshot(self) -> dict[str, float | int]:
        return {
            "cash": self.cash,
            "total_value": self.cash + 2400.0,
            "equity": self.cash + 2400.0,
            "positions": 1,
            "drawdown": -0.012,
            "peak_equity": self._peak_equity,
        }


class _FakePosition:
    def __init__(self) -> None:
        self.symbol = "BTC/USDT"
        self.quantity = 0.05
        self.entry_price = 48000.0
        self.current_price = 48500.0
        self.unrealized_pnl = 25.0
        self.strategy_id = "trend_following"

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price


class _FakePositionManager:
    total_market_value = 2425.0

    def get_all_positions(self) -> list[object]:
        return [_FakePosition()]


class _EnumValue:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeOrder:
    def __init__(self) -> None:
        self.order_id = "ord-1"
        self.symbol = "BTC/USDT"
        self.side = _EnumValue("buy")
        self.order_type = "limit"
        self.status = _EnumValue("open")
        self.quantity = 0.02
        self.price = 47000.0
        self.strategy_id = "trend_following"


class _FakeOrderManager:
    def get_open_orders(self) -> list[object]:
        return [_FakeOrder()]


class _FakeExecution:
    def __init__(self) -> None:
        self.position_manager = _FakePositionManager()
        self.order_manager = _FakeOrderManager()


class _FakeKillSwitch:
    def __init__(self) -> None:
        self.is_active = False
        self.reason: str | None = None

    async def activate(self, reason: str) -> dict[str, object]:
        self.is_active = True
        self.reason = reason
        return {"active": True, "reason": reason}

    def check(self) -> dict[str, object]:
        return {"active": self.is_active, "reason": self.reason}


class _FakeTradingSession:
    def __init__(self, config, strategies) -> None:
        self.config = config
        self.strategies = strategies
        self._event_bus = EventBus()
        self.execution = _FakeExecution()
        self.portfolio = _FakePortfolio()
        self._kill_switch = _FakeKillSwitch()
        self._running = True

    async def start(self, mode: str = "paper", gateway_config=None) -> None:
        self.mode = mode
        self.gateway_config = gateway_config

    async def run_data_loop(
        self,
        symbol: str,
        timeframe: str = "1h",
        interval_seconds: int = 60,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.interval_seconds = interval_seconds
        await asyncio.sleep(3600)

    async def stop(self) -> None:
        self._running = False

    def check_health(self) -> dict[str, object]:
        return {
            "running": self._running,
            "drawdown_ok": True,
            "pending_orders": 1,
            "open_positions": 1,
        }

    def adjust_capital(self, capital: float) -> None:
        self.portfolio.set_capital_baseline(capital)

    def snapshot_state(self) -> dict[str, object]:
        market_value = self.execution.position_manager.total_market_value
        portfolio = self.portfolio.snapshot()
        portfolio["market_value"] = market_value
        portfolio["equity"] = self.portfolio.cash + market_value
        portfolio["total_value"] = self.portfolio.cash + market_value
        return {
            "health": self.check_health(),
            "cash": self.portfolio.cash,
            "portfolio": portfolio,
            "positions": [
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "entry_price": p.entry_price,
                    "current_price": p.current_price,
                    "market_value": p.market_value,
                    "unrealized_pnl": p.unrealized_pnl,
                    "strategy_id": getattr(p, "strategy_id", ""),
                }
                for p in self.execution.position_manager.get_all_positions()
            ],
            "open_orders": [
                {
                    "order_id": o.order_id,
                    "symbol": o.symbol,
                    "side": o.side.value,
                    "order_type": o.order_type,
                    "status": o.status.value,
                    "quantity": o.quantity,
                    "price": o.price,
                    "strategy_id": getattr(o, "strategy_id", ""),
                }
                for o in self.execution.order_manager.get_open_orders()
            ],
            "kill_switch": self._kill_switch.check(),
        }

    async def activate_kill_switch(self, reason: str):
        return await self._kill_switch.activate(reason)

    @property
    def kill_switch(self) -> _FakeKillSwitch:
        return self._kill_switch


@pytest.mark.asyncio
async def test_station_session_manager_records_lifecycle_and_signal_events(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metric_updates: list[dict[str, float | int]] = []
    monkeypatch.setattr(
        "quantflow.web.session_manager.load_config",
        lambda path: SimpleNamespace(execution=SimpleNamespace(mode="paper")),
    )
    monkeypatch.setattr(
        "quantflow.web.session_manager.get_strategy_factories",
        lambda: {"trend_following": lambda _: SimpleNamespace(name="trend_following")},
    )
    monkeypatch.setattr("quantflow.web.session_manager.TradingSession", _FakeTradingSession)
    monkeypatch.setattr(
        "quantflow.web.session_manager.update_portfolio_metrics",
        lambda **kwargs: metric_updates.append(kwargs),
    )

    store = StationHistoryStore(base_dir=tmp_path / "station_history")
    manager = StationSessionManager(history_store=store)

    snapshot = await manager.start(
        SessionStartRequest(
            mode="paper",
            strategies=["trend_following"],
            symbol="BTC/USDT",
            timeframe="1h",
            interval_seconds=30,
        )
    )
    assert snapshot["running"] is True
    session_id = snapshot["session_id"]
    assert snapshot["updated_at"] is not None
    assert snapshot["telemetry"]["labels"]
    assert snapshot["event_summary"]["total"] >= 1
    assert snapshot["dashboard"]["status_label"] == "Running"
    assert snapshot["positions"][0]["side"] == "long"
    assert snapshot["positions"][0]["market_value"] == pytest.approx(2425.0)
    assert snapshot["positions"][0]["pnl_pct"] == pytest.approx(25.0 / (48000.0 * 0.05))
    assert snapshot["open_orders"][0]["order_type"] == "limit"
    assert snapshot["open_orders"][0]["notional"] == pytest.approx(940.0)
    assert metric_updates[-1]["cash"] == pytest.approx(100000.0)
    assert metric_updates[-1]["total_value"] == pytest.approx(102425.0)
    assert metric_updates[-1]["drawdown"] == pytest.approx(-0.012)
    assert metric_updates[-1]["n_positions"] == 1

    runtime = manager._runtime
    assert runtime is not None
    runtime.session._event_bus.publish(
        Event(
            EVENT_SIGNAL,
            {
                "strategy_id": "trend_following",
                "symbol": "BTC/USDT",
                "direction": 1,
                "strength": 0.8,
            },
        )
    )

    events = await manager.events(session_id=session_id)
    event_types = [item["event_type"] for item in events["items"]]
    assert "signal" in event_types
    assert "session_started" in event_types

    kill_result = await manager.trigger_kill_switch("manual_test")
    assert kill_result["reason"] == "manual_test"

    stopped_snapshot = await manager.stop()
    assert stopped_snapshot["running"] is False
    assert stopped_snapshot["dashboard"]["status_label"] == "Kill Switch"
    assert stopped_snapshot["dashboard"]["status_tone"] == "danger"
    assert stopped_snapshot["event_summary"]["by_type"]["kill_switch"] >= 1

    history = await manager.session_history(limit=5)
    assert history["items"][0]["session_id"] == session_id
    assert history["items"][0]["running"] is False

    persisted_events = store.list_session_events(limit=10, session_id=session_id)
    assert any(item["event_type"] == "kill_switch" for item in persisted_events)
    assert any(item["event_type"] == "session_stopped" for item in persisted_events)


def test_append_rejects_unknown_category(tmp_path) -> None:
    """ISS-009: a path-shaped or unknown category must not escape base_dir."""
    store = StationHistoryStore(base_dir=tmp_path / "station_history")
    with pytest.raises(ValueError, match="unknown history category"):
        store._append("../escape", {"record_id": "x"})  # type: ignore[operator]
    # base_dir has no sibling escape file
    assert not (tmp_path / "escape.jsonl").exists()


def test_append_truncates_oversized_record(tmp_path) -> None:
    """ISS-009 (SEC-018): a record whose JSON line exceeds the per-line cap is
    written as a capped placeholder, not the megabyte blob."""
    from quantflow.web.history import _MAX_JSONL_LINE_BYTES

    store = StationHistoryStore(base_dir=tmp_path / "station_history")
    # Payload larger than the 256KiB line cap.
    huge_payload = "X" * (_MAX_JSONL_LINE_BYTES + 4096)
    record = store.append_session_event(
        {"session_id": "session-big", "event_type": "signal", "payload": huge_payload}
    )
    events = store.list_session_events(limit=5, session_id="session-big")
    assert len(events) == 1
    item = events[0]
    # The payload blob was dropped; the line is well under the cap.
    assert "_truncated" in item
    assert "payload" not in item
    assert item["session_id"] == "session-big"
    assert item["event_type"] == "signal"
    # record_id/created_at preserved (audit continuity).
    assert item["record_id"] == record["record_id"]
    assert item["created_at"] == record["created_at"]
    # Sanity: no file line exceeds the cap.
    lines = (
        (tmp_path / "station_history" / "session_events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert all(len(line.encode("utf-8")) <= _MAX_JSONL_LINE_BYTES for line in lines)


def test_append_keeps_normal_sized_record(tmp_path) -> None:
    """A normal-sized record is written verbatim, never truncated."""
    store = StationHistoryStore(base_dir=tmp_path / "station_history")
    store.append_session_event(
        {"session_id": "session-ok", "event_type": "signal", "strength": 0.5}
    )
    events = store.list_session_events(limit=5, session_id="session-ok")
    assert events[0].get("_truncated") is None
    assert events[0]["strength"] == 0.5
