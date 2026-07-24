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
    SIGNAL_PROCESSING_LATENCY,
    SIGNALS_GENERATED,
    start_metrics_server,
    update_portfolio_metrics,
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
