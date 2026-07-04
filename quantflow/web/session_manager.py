"""Background trading-session management for QuantFlow Station."""

from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from quantflow.common.config import load_config
from quantflow.common.event_bus import Event, EventBus
from quantflow.common.models import EVENT_FILL, EVENT_ORDER, EVENT_RISK, EVENT_SIGNAL
from quantflow.execution.kill_switch import KillSwitch
from quantflow.monitoring.metrics import update_portfolio_metrics
from quantflow.strategy.catalog import get_strategy_factories
from quantflow.strategy.engine import TradingSession
from quantflow.web.history import StationHistoryStore

DEFAULT_CONFIG_PATH = "quantflow/config/default.yaml"
MAX_TELEMETRY_POINTS = 240
MIN_TELEMETRY_INTERVAL_SECONDS = 4
EVENT_SUMMARY_LIMIT = 80


def _gateway_config_from_env(mode: str, sandbox: bool) -> dict[str, str | bool]:
    import os

    gateway_config: dict[str, str | bool] = {"sandbox": sandbox}
    if mode == "paper":
        return gateway_config

    required = {
        "OKX_API_KEY": "api_key",
        "OKX_SECRET": "secret",
        "OKX_PASSPHRASE": "passphrase",
    }
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"Missing required environment variables for {mode} mode: {missing_text}")

    for env_name, config_key in required.items():
        gateway_config[config_key] = os.environ[env_name]
    return gateway_config


class SessionStartRequest(BaseModel):
    mode: str = "paper"
    strategies: list[str] = Field(default_factory=lambda: ["trend_following"])
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    interval_seconds: int = 60
    capital: float = 100000.0
    config_path: str = DEFAULT_CONFIG_PATH


@dataclass
class SessionRuntime:
    session_id: str
    session: TradingSession
    loop_task: asyncio.Task[None]
    request: SessionStartRequest
    started_at: str
    last_error: str | None = None
    event_handlers: list[tuple[str, Any]] = field(default_factory=list)
    telemetry_points: list[dict[str, Any]] = field(default_factory=list)


def _safe_number(value: Any) -> Any:
    if isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return _safe_number(value)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _format_duration(total_seconds: int) -> str:
    total_seconds = max(0, total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    if minutes > 0:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


class StationSessionManager:
    """Own the single active web-managed trading session."""

    def __init__(
        self,
        config_path: str = DEFAULT_CONFIG_PATH,
        history_store: StationHistoryStore | None = None,
    ) -> None:
        self._config_path = config_path
        self._history_store = history_store or StationHistoryStore()
        self._runtime: SessionRuntime | None = None
        self._lock = asyncio.Lock()

    async def start(self, request: SessionStartRequest) -> dict[str, Any]:
        async with self._lock:
            if self._runtime and not self._runtime.loop_task.done():
                raise RuntimeError("A trading session is already running.")

            config = load_config(request.config_path or self._config_path)
            config.execution.mode = request.mode
            strategy_factories = get_strategy_factories()
            strategies = []
            for strategy_name in request.strategies:
                factory = strategy_factories.get(strategy_name)
                if factory is None:
                    raise ValueError(f"Unknown strategy: {strategy_name}")
                strategies.append(factory(None))

            session = TradingSession(config, strategies)
            cash_delta = request.capital - session.portfolio.cash
            if abs(cash_delta) > 1e-10:
                session.portfolio.update_cash(cash_delta)
                if hasattr(session.portfolio, "_initial_capital"):
                    session.portfolio._initial_capital = request.capital
                if hasattr(session.portfolio, "_peak_equity"):
                    session.portfolio._peak_equity = request.capital
            gateway_config = _gateway_config_from_env(
                request.mode,
                sandbox=(request.mode == "sandbox"),
            )
            await session.start(mode=request.mode, gateway_config=gateway_config)
            session_id = self._build_session_id()

            loop_task = asyncio.create_task(
                session.run_data_loop(
                    symbol=request.symbol,
                    timeframe=request.timeframe,
                    interval_seconds=request.interval_seconds,
                ),
                name="quantflow-station-data-loop",
            )
            runtime = SessionRuntime(
                session_id=session_id,
                session=session,
                loop_task=loop_task,
                request=request,
                started_at=datetime.now(UTC).isoformat(),
            )
            self._attach_event_observers(runtime)
            self._record_lifecycle_event(
                runtime,
                event_type="session_started",
                title="Session started",
                level="info",
                message=(
                    f"{request.mode} {request.symbol} {request.timeframe} "
                    f"with {', '.join(request.strategies)}"
                ),
            )
            loop_task.add_done_callback(lambda task: self._capture_task_outcome(task, runtime))
            self._runtime = runtime
            snapshot = await self.snapshot()
            self._history_store.append_session_snapshot(snapshot)
            return snapshot

    def _capture_task_outcome(self, task: asyncio.Task[None], runtime: SessionRuntime) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            runtime.last_error = None
        except Exception as exc:
            runtime.last_error = str(exc)
            self._record_lifecycle_event(
                runtime,
                event_type="session_error",
                title="Session error",
                level="error",
                message=str(exc),
                data={"source": "data_loop"},
            )

    async def stop(self) -> dict[str, Any]:
        async with self._lock:
            if self._runtime is None:
                return self._empty_snapshot()

            runtime = self._runtime
            if not runtime.loop_task.done():
                runtime.loop_task.cancel()
                with suppress(asyncio.CancelledError):
                    await runtime.loop_task
            await runtime.session.stop()
            self._record_lifecycle_event(
                runtime,
                event_type="session_stopped",
                title="Session stopped",
                level="info",
                message="Trading session stopped by operator.",
            )
            snapshot = self._build_snapshot(runtime, running_override=False)
            self._history_store.append_session_snapshot(snapshot)
            self._detach_event_observers(runtime)
            self._runtime = None
            return snapshot

    async def trigger_kill_switch(self, reason: str) -> dict[str, Any]:
        async with self._lock:
            if self._runtime is None or self._runtime.session.kill_switch is None:
                raise RuntimeError("No active session kill switch is available.")
            kill_switch: KillSwitch = self._runtime.session.kill_switch
            result = await kill_switch.activate(reason)
            self._record_lifecycle_event(
                self._runtime,
                event_type="kill_switch",
                title="Kill switch activated",
                level="critical",
                message=f"Kill switch activated: {reason}",
                data={"reason": reason},
            )
            return result

    async def events(self, limit: int = 40, session_id: str | None = None) -> dict[str, Any]:
        active_session_id = session_id
        if active_session_id is None and self._runtime is not None:
            active_session_id = self._runtime.session_id
        return {
            "items": self._history_store.list_session_events(
                limit=limit,
                session_id=active_session_id,
            )
        }

    async def session_history(self, limit: int = 12) -> dict[str, Any]:
        live_session_id = None
        if self._runtime is not None and not self._runtime.loop_task.done():
            live_session_id = self._runtime.session_id
        items = [
            self._present_session_snapshot(item, live_session_id=live_session_id)
            for item in self._history_store.list_session_snapshots(limit=limit)
        ]
        return {"items": items}

    async def snapshot(self) -> dict[str, Any]:
        runtime = self._runtime
        if runtime is None:
            return self._empty_snapshot()

        return self._build_snapshot(runtime)

    def _build_snapshot(
        self,
        runtime: SessionRuntime,
        *,
        running_override: bool | None = None,
    ) -> dict[str, Any]:
        captured_at = _now_utc()
        running = running_override
        if running is None:
            running = not runtime.loop_task.done()

        health = runtime.session.check_health()
        cash = runtime.session.portfolio.cash
        market_value = runtime.session.execution.position_manager.total_market_value
        portfolio = runtime.session.portfolio.snapshot()
        portfolio["market_value"] = market_value
        portfolio["equity"] = cash + market_value
        portfolio["total_value"] = cash + market_value
        update_portfolio_metrics(
            total_value=float(portfolio["total_value"]),
            cash=float(portfolio["cash"]),
            drawdown=float(portfolio.get("drawdown", 0.0) or 0.0),
            n_positions=int(portfolio.get("positions", 0) or 0),
        )
        positions = [
            {
                "symbol": position.symbol,
                "quantity": position.quantity,
                "side": "long" if position.quantity > 0 else "short" if position.quantity < 0 else "flat",
                "entry_price": position.entry_price,
                "current_price": position.current_price,
                "market_value": position.quantity * position.current_price,
                "unrealized_pnl": position.unrealized_pnl,
                "pnl_pct": (
                    position.unrealized_pnl / abs(position.entry_price * position.quantity)
                    if position.entry_price and position.quantity
                    else 0.0
                ),
            }
            for position in runtime.session.execution.position_manager.get_all_positions()
        ]
        open_orders = [
            {
                "order_id": order.order_id,
                "symbol": order.symbol,
                "side": order.side.value,
                "order_type": order.order_type,
                "status": order.status.value,
                "quantity": order.quantity,
                "price": order.price,
                "notional": order.quantity * order.price if order.price is not None else None,
                "strategy_id": order.strategy_id,
            }
            for order in runtime.session.execution.order_manager.get_open_orders()
        ]
        recent_events = self._history_store.list_session_events(
            limit=40,
            session_id=runtime.session_id,
        )
        snapshot = {
            "session_id": runtime.session_id,
            "running": running and health.get("running", False),
            "started_at": runtime.started_at,
            "updated_at": captured_at.isoformat(),
            "request": runtime.request.model_dump(),
            "health": health,
            "portfolio": portfolio,
            "positions": positions,
            "open_orders": open_orders,
            "kill_switch": runtime.session.kill_switch.check()
            if runtime.session.kill_switch is not None
            else {"active": False, "reason": None},
            "last_error": runtime.last_error or getattr(runtime.session, "last_error", None),
            "recent_events": recent_events[:12],
        }
        self._record_telemetry_point(runtime, snapshot, captured_at)
        snapshot["telemetry"] = self._telemetry_payload(runtime)
        snapshot["event_summary"] = self._event_summary(recent_events)
        snapshot["dashboard"] = self._dashboard_payload(runtime, snapshot, recent_events)
        return snapshot

    @staticmethod
    def _present_session_snapshot(
        snapshot: dict[str, Any],
        *,
        live_session_id: str | None = None,
    ) -> dict[str, Any]:
        record = dict(snapshot)
        recorded_running = bool(record.get("running"))
        is_live = bool(live_session_id) and record.get("session_id") == live_session_id
        effective_running = recorded_running and is_live

        record["recorded_running"] = recorded_running
        record["is_live"] = is_live
        record["running"] = effective_running

        health = dict(record.get("health") or {})
        if health:
            health["running"] = effective_running
            record["health"] = health

        dashboard = dict(record.get("dashboard") or {})
        if dashboard:
            if not effective_running and dashboard.get("status_label") == "Running":
                dashboard["status_label"] = "Stopped"
            if not effective_running and dashboard.get("status_tone") == "accent":
                dashboard["status_tone"] = "muted"
            record["dashboard"] = dashboard

        return record

    async def cleanup(self) -> None:
        await self.stop()

    @staticmethod
    def _build_session_id() -> str:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        return f"station-{stamp}-{uuid4().hex[:6]}"

    def _attach_event_observers(self, runtime: SessionRuntime) -> None:
        event_bus = getattr(runtime.session, "_event_bus", None)
        if not isinstance(event_bus, EventBus):
            return

        for event_type in (EVENT_SIGNAL, EVENT_ORDER, EVENT_FILL, EVENT_RISK):
            handler = self._build_event_handler(runtime, event_type)
            event_bus.subscribe(event_type, handler)
            runtime.event_handlers.append((event_type, handler))

    def _detach_event_observers(self, runtime: SessionRuntime) -> None:
        event_bus = getattr(runtime.session, "_event_bus", None)
        if not isinstance(event_bus, EventBus):
            return
        for event_type, handler in runtime.event_handlers:
            event_bus.unsubscribe(event_type, handler)
        runtime.event_handlers.clear()

    def _build_event_handler(self, runtime: SessionRuntime, event_type: str):
        def handler(event: Event) -> None:
            payload = _jsonable(event.data or {})
            title, level, message = self._describe_event(event_type, payload)
            self._history_store.append_session_event(
                {
                    "session_id": runtime.session_id,
                    "event_type": event_type,
                    "title": title,
                    "level": level,
                    "message": message,
                    "data": payload,
                }
            )

        return handler

    def _record_lifecycle_event(
        self,
        runtime: SessionRuntime,
        *,
        event_type: str,
        title: str,
        level: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        self._history_store.append_session_event(
            {
                "session_id": runtime.session_id,
                "event_type": event_type,
                "title": title,
                "level": level,
                "message": message,
                "data": _jsonable(data or {}),
            }
        )

    def _empty_snapshot(self) -> dict[str, Any]:
        return {
            "session_id": None,
            "running": False,
            "started_at": None,
            "updated_at": None,
            "request": None,
            "health": {
                "running": False,
                "drawdown_ok": True,
                "pending_orders": 0,
                "open_positions": 0,
            },
            "portfolio": {
                "cash": 0.0,
                "market_value": 0.0,
                "equity": 0.0,
                "total_value": 0.0,
                "positions": 0,
                "drawdown": 0.0,
                "peak_equity": 0.0,
            },
            "positions": [],
            "open_orders": [],
            "kill_switch": {"active": False, "reason": None},
            "last_error": None,
            "recent_events": [],
            "telemetry": {
                "labels": [],
                "equity": [],
                "cash": [],
                "market_value": [],
                "drawdown": [],
                "open_positions": [],
                "pending_orders": [],
            },
            "event_summary": {"total": 0, "by_type": {}, "by_level": {}},
            "dashboard": {
                "mode": "paper",
                "symbol": "N/A",
                "timeframe": "N/A",
                "strategies": [],
                "strategy_count": 0,
                "uptime_seconds": 0,
                "uptime_label": "0s",
                "status_label": "Stopped",
                "status_tone": "muted",
                "exposure_pct": 0.0,
                "gross_exposure_pct": 0.0,
                "gross_exposure_value": 0.0,
                "net_exposure_value": 0.0,
                "recent_event_count": 0,
                "warning_event_count": 0,
                "error_event_count": 0,
                "signal_count": 0,
                "fill_count": 0,
                "risk_count": 0,
                "open_positions": 0,
                "pending_orders": 0,
            },
        }

    def _record_telemetry_point(
        self,
        runtime: SessionRuntime,
        snapshot: dict[str, Any],
        captured_at: datetime,
    ) -> None:
        portfolio = snapshot["portfolio"]
        health = snapshot["health"]
        point = {
            "timestamp": captured_at.isoformat(),
            "running": snapshot["running"],
            "equity": _safe_number(portfolio.get("equity", 0.0)),
            "cash": _safe_number(portfolio.get("cash", 0.0)),
            "market_value": _safe_number(portfolio.get("market_value", 0.0)),
            "drawdown": _safe_number(portfolio.get("drawdown", 0.0)),
            "open_positions": int(health.get("open_positions", len(snapshot["positions"]))),
            "pending_orders": int(health.get("pending_orders", len(snapshot["open_orders"]))),
        }

        if runtime.telemetry_points:
            last_point = runtime.telemetry_points[-1]
            last_at = datetime.fromisoformat(str(last_point["timestamp"]))
            same_state = (
                last_point.get("running") == point["running"]
                and last_point.get("equity") == point["equity"]
                and last_point.get("market_value") == point["market_value"]
                and last_point.get("drawdown") == point["drawdown"]
                and last_point.get("open_positions") == point["open_positions"]
                and last_point.get("pending_orders") == point["pending_orders"]
            )
            if (captured_at - last_at).total_seconds() < MIN_TELEMETRY_INTERVAL_SECONDS and same_state:
                runtime.telemetry_points[-1] = point
            else:
                runtime.telemetry_points.append(point)
        else:
            runtime.telemetry_points.append(point)

        if len(runtime.telemetry_points) > MAX_TELEMETRY_POINTS:
            runtime.telemetry_points = runtime.telemetry_points[-MAX_TELEMETRY_POINTS:]

    @staticmethod
    def _telemetry_payload(runtime: SessionRuntime) -> dict[str, list[Any]]:
        points = runtime.telemetry_points[-MAX_TELEMETRY_POINTS:]
        return {
            "labels": [point["timestamp"] for point in points],
            "equity": [point["equity"] for point in points],
            "cash": [point["cash"] for point in points],
            "market_value": [point["market_value"] for point in points],
            "drawdown": [point["drawdown"] for point in points],
            "open_positions": [point["open_positions"] for point in points],
            "pending_orders": [point["pending_orders"] for point in points],
        }

    @staticmethod
    def _event_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
        limited = events[:EVENT_SUMMARY_LIMIT]
        by_type = Counter(str(item.get("event_type", "unknown")) for item in limited)
        by_level = Counter(str(item.get("level", "info")) for item in limited)
        return {
            "total": len(limited),
            "by_type": dict(by_type),
            "by_level": dict(by_level),
        }

    def _dashboard_payload(
        self,
        runtime: SessionRuntime,
        snapshot: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        portfolio = snapshot["portfolio"]
        health = snapshot["health"]
        kill_switch = snapshot["kill_switch"]
        event_summary = self._event_summary(events)
        now = _now_utc()
        started_at = datetime.fromisoformat(runtime.started_at)
        uptime_seconds = int((now - started_at).total_seconds())
        equity = float(portfolio.get("equity", 0.0) or 0.0)
        market_value = float(portfolio.get("market_value", 0.0) or 0.0)
        gross_exposure_value = sum(abs(float(item.get("market_value", 0.0) or 0.0)) for item in snapshot["positions"])
        exposure_pct = market_value / equity if equity > 0 else 0.0

        status_label = "Stopped"
        status_tone = "muted"
        if kill_switch.get("active"):
            status_label = "Kill Switch"
            status_tone = "danger"
        elif snapshot["last_error"]:
            status_label = "Degraded"
            status_tone = "warning"
        elif snapshot["running"]:
            status_label = "Running"
            status_tone = "accent"

        return {
            "mode": runtime.request.mode,
            "symbol": runtime.request.symbol,
            "timeframe": runtime.request.timeframe,
            "strategies": list(runtime.request.strategies),
            "strategy_count": len(runtime.request.strategies),
            "uptime_seconds": uptime_seconds,
            "uptime_label": _format_duration(uptime_seconds),
            "status_label": status_label,
            "status_tone": status_tone,
            "exposure_pct": exposure_pct,
            "gross_exposure_pct": gross_exposure_value / equity if equity > 0 else 0.0,
            "gross_exposure_value": gross_exposure_value,
            "net_exposure_value": market_value,
            "recent_event_count": event_summary["total"],
            "warning_event_count": event_summary["by_level"].get("warning", 0),
            "error_event_count": event_summary["by_level"].get("error", 0)
            + event_summary["by_level"].get("critical", 0),
            "signal_count": event_summary["by_type"].get(EVENT_SIGNAL, 0),
            "fill_count": event_summary["by_type"].get(EVENT_FILL, 0),
            "risk_count": event_summary["by_type"].get(EVENT_RISK, 0),
            "open_positions": int(health.get("open_positions", len(snapshot["positions"]))),
            "pending_orders": int(health.get("pending_orders", len(snapshot["open_orders"]))),
        }

    @staticmethod
    def _describe_event(event_type: str, payload: dict[str, Any]) -> tuple[str, str, str]:
        if event_type == EVENT_SIGNAL:
            strategy = payload.get("strategy_id", "unknown")
            direction = payload.get("direction", "n/a")
            symbol = payload.get("symbol", "n/a")
            strength = payload.get("strength", "n/a")
            return (
                "Signal generated",
                "info",
                f"{strategy} emitted {direction} on {symbol} (strength={strength}).",
            )
        if event_type == EVENT_ORDER:
            status = str(payload.get("status", "submitted")).lower()
            side = payload.get("side", "n/a")
            symbol = payload.get("symbol", "n/a")
            if status == "filled":
                return (
                    "Order filled",
                    "success",
                    f"{side} order for {symbol} is filled.",
                )
            if status == "rejected":
                return (
                    "Order rejected",
                    "error",
                    f"{side} order for {symbol} is rejected.",
                )
            if status == "cancelled":
                return (
                    "Order cancelled",
                    "warning",
                    f"{side} order for {symbol} is cancelled.",
                )
            return (
                "Order submitted",
                "info",
                f"{side} order for {symbol} is {status}.",
            )
        if event_type == EVENT_FILL:
            return (
                "Order filled",
                "success",
                f"{payload.get('side', 'n/a')} {payload.get('quantity', 'n/a')} "
                f"{payload.get('symbol', 'n/a')} @ {payload.get('price', 'n/a')}.",
            )
        risk_type = payload.get("type", "risk_event")
        return (
            "Risk event",
            "warning",
            f"{risk_type}: {payload.get('reason', 'risk constraint triggered')}.",
        )
