"""Default MonitoringSink — L6 implementation of the common/ seam (ISS-019).

This is the concrete sink: it wires Prometheus metrics + AlertManager. It
lives in ``monitoring/`` (L6 owns L6 logic) and is injected into lower layers
by the caller (cli / session_manager) — lower layers depend only on the
``common.monitoring_sink.MonitoringSink`` Protocol, never on this module.

Extracted from ``strategy/engine.py`` which previously imported
``monitoring.metrics`` + ``monitoring.alerts`` directly (ISS-019 L3->L6
coupling). The metrics-push and alert-send calls move here verbatim; only the
call site changes (TradingSession calls ``self._sink.record_*`` /
``await self._sink.send_alert`` instead of the module-level functions).
"""

from __future__ import annotations

import logging
from typing import Any

from quantflow.monitoring.alerts import AlertLevel, AlertManager
from quantflow.monitoring.metrics import (
    BAR_PROCESSING_LATENCY,
    GATEWAY_CONNECTED,
    GATEWAY_DISCONNECTS,
    GATEWAY_RECONNECTS,
    KILL_SWITCH_ACTIVATIONS,
    KILL_SWITCH_STEP_FAILURES,
    ORDER_LATENCY,
    ORDERS_FILLED,
    ORDERS_TIMED_OUT,
    ORDERS_TOTAL,
    PORTFOLIO_ALLOCATION,
    RISK_EVENTS,
    SIGNAL_PROCESSING_LATENCY,
    SIGNALS_GENERATED,
    STRATEGY_BUDGET_UTILIZATION,
    STRATEGY_PNL,
    start_metrics_server,
    update_portfolio_metrics,
    update_research_go_panel_metrics,
)

logger = logging.getLogger(__name__)

# Map the Protocol's plain-string level to the AlertLevel enum the AlertManager
# consumes. Kept here (not in common/) so the Protocol stays free of L6 types.
_LEVEL_MAP = {
    "info": AlertLevel.INFO,
    "warning": AlertLevel.WARNING,
    "critical": AlertLevel.CRITICAL,
}


class DefaultMonitoringSink:
    """Concrete sink: Prometheus metrics + AlertManager alerts.

    Constructed by ``create_default_sink`` from the app config; injected into
    TradingSession. Holds the AlertManager instance (it needs telegram token/
    chat_id from config) so TradingSession no longer owns alert-channel wiring.
    """

    def __init__(self) -> None:
        self._alert_mgr: AlertManager | None = None

    def start(self, config: Any) -> None:
        """Start the metrics server once per process + wire alert channels.

        start_metrics_server is idempotent per port (ISS-019: moved the
        attempt-set dedup into metrics.py), so repeat calls are safe.
        """
        start_metrics_server(config.monitoring.prometheus_port)
        channels = config.monitoring.alert_channels
        if channels:
            ch = channels[0]
            self._alert_mgr = AlertManager(
                telegram_token=ch.token,
                telegram_chat_id=ch.chat_id,
            )

    def record_signal(self, strategy_id: str, direction: str) -> None:
        SIGNALS_GENERATED.labels(
            strategy_id=strategy_id,
            direction=direction,
        ).inc()

    def record_bar_latency(self, symbol: str, duration_seconds: float) -> None:
        BAR_PROCESSING_LATENCY.labels(symbol=symbol).observe(duration_seconds)

    def record_signal_latency(self, strategy_id: str, duration_seconds: float) -> None:
        SIGNAL_PROCESSING_LATENCY.labels(strategy_id=strategy_id).observe(duration_seconds)

    def record_portfolio(
        self,
        total_value: float,
        cash: float,
        drawdown: float,
        n_positions: int,
    ) -> None:
        update_portfolio_metrics(
            total_value=total_value,
            cash=cash,
            drawdown=drawdown,
            n_positions=n_positions,
        )

    def record_risk_event(self, event_type: str, severity: str) -> None:
        # L4 risk_engine seam (ISS-20260724-044): replaced the in-function
        # `from quantflow.monitoring.metrics import RISK_EVENTS` lazy-import.
        RISK_EVENTS.labels(event_type=event_type, severity=severity).inc()

    def record_kill_switch_activation(self, reason: str) -> None:
        # L5 kill_switch seam (ISS-20260724-044): replaced the top-level
        # KILL_SWITCH_ACTIVATIONS import.
        KILL_SWITCH_ACTIVATIONS.labels(reason=reason).inc()

    def record_kill_switch_step_failure(self, step: str) -> None:
        # L5 kill_switch seam (ISS-20260724-044): per-step failure counter.
        KILL_SWITCH_STEP_FAILURES.labels(step=step).inc()

    def record_order_total(self, symbol: str, side: str, strategy_id: str) -> None:
        # L5 execution/engine seam (ISS-20260724-044): replaced the top-level
        # ORDERS_TOTAL import.
        ORDERS_TOTAL.labels(symbol=symbol, side=side, strategy_id=strategy_id).inc()

    def record_order_filled(self, symbol: str, side: str, strategy_id: str) -> None:
        # L5 execution/engine seam (ISS-20260724-044): replaced ORDERS_FILLED.
        ORDERS_FILLED.labels(symbol=symbol, side=side, strategy_id=strategy_id).inc()

    def record_order_latency(self, symbol: str, duration_seconds: float) -> None:
        # L5 execution/engine seam (ISS-20260724-044): replaced ORDER_LATENCY.
        ORDER_LATENCY.labels(symbol=symbol).observe(duration_seconds)

    def record_gateway_connected(self, exchange: str, connected: bool) -> None:
        # L5 okx_gateway seam (ISS-20260723-011 OBS-M): liveness gauge — set
        # (not inc) so it reflects current state, not a cumulative tally.
        GATEWAY_CONNECTED.labels(exchange=exchange).set(1 if connected else 0)

    def record_gateway_disconnect(self, exchange: str, reason: str) -> None:
        # L5 okx_gateway seam (ISS-20260723-011 OBS-M): disconnect counter by
        # trigger reason (timeout/error/shutdown).
        GATEWAY_DISCONNECTS.labels(exchange=exchange, reason=reason).inc()

    def record_gateway_reconnect(self, exchange: str, success: bool) -> None:
        # L5 okx_gateway seam (ISS-20260723-011 OBS-M): reconnect counter by
        # outcome — repeated success=False alerts on a flapping exchange.
        GATEWAY_RECONNECTS.labels(exchange=exchange, success="true" if success else "false").inc()

    def record_order_timed_out(self, symbol: str, side: str) -> None:
        # L5 order_manager seam (ISS-20260723-011 OBS-M): stale-order churn
        # counter — orders that exceeded the watchdog window and were cancelled.
        ORDERS_TIMED_OUT.labels(symbol=symbol, side=side).inc()

    def record_strategy_pnl(
        self, strategy_id: str, pnl: float, budget_utilization: float | None = None
    ) -> None:
        # s4 (T-s4-05): strategy-level PnL attribution + budget utilization.
        # Strategy granularity matches the strategy_id labels on signal/order
        # metrics, so a single Grafana strategy panel can join them.
        STRATEGY_PNL.labels(strategy_id=strategy_id).set(float(pnl))
        if budget_utilization is not None:
            STRATEGY_BUDGET_UTILIZATION.labels(strategy_id=strategy_id).set(
                float(budget_utilization)
            )

    def record_portfolio_allocation(self, weights: dict[str, float]) -> None:
        # s5 follow-up: per-strategy allocation weight gauge, updated after
        # each rebalance. Best-effort — a sink must never raise.
        for strategy_id, w in weights.items():
            PORTFOLIO_ALLOCATION.labels(strategy_id=strategy_id).set(float(w))

    def record_research_go_panel(self, snapshot: Any) -> None:
        """Best-effort push of the sealed research GO panel into gauges.

        L6 research GO export (off hot path): delegates to
        ``update_research_go_panel_metrics`` which no-ops on None. A sink
        must never raise into callers — any unexpected failure is logged.
        """
        try:
            update_research_go_panel_metrics(snapshot)
        except Exception:
            logger.exception("record_research_go_panel failed (fail-soft)")

    async def send_alert(
        self,
        message: str,
        level: str = "warning",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, bool]:
        if self._alert_mgr is None:
            return {}
        return await self._alert_mgr.send(
            message,
            _LEVEL_MAP.get(level, AlertLevel.WARNING),
            extra=extra,
        )


def create_default_sink() -> DefaultMonitoringSink:
    """Factory for the concrete sink — callers inject this into TradingSession.

    Kept as a function (not ``DefaultMonitoringSink()`` inline) so tests can
    monkeypatch the factory if needed.
    """
    return DefaultMonitoringSink()
