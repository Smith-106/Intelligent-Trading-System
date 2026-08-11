"""Session health snapshot export (IMP-05).

Builds a JSON-serializable health document for paper/live sessions without
depending on a live TradingSession instance (pure function / optional gauges).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from quantflow.monitoring.alerts import (
    ALERT_ROUTING,
    AlertCategory,
    AlertLevel,
    AlertPriority,
    resolve_alert_channels,
)
from quantflow.monitoring.metrics import update_session_health


@dataclass
class SessionHealthSnapshot:
    """Readable session health for ops dashboards / CLI."""

    mode: str
    strategy_id: str
    up: bool
    bars_processed: int = 0
    last_bar_age_seconds: float = 0.0
    open_orders: int = 0
    portfolio_value: float | None = None
    drawdown: float | None = None
    kill_switch_active: bool = False
    gateway_connected: bool | None = None
    notes: list[str] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if not d.get("generated_at"):
            d["generated_at"] = datetime.now(UTC).isoformat()
        return d

    @property
    def status(self) -> str:
        if self.kill_switch_active:
            return "halted"
        if not self.up:
            return "down"
        if self.last_bar_age_seconds > 3600:
            return "stale"
        if self.gateway_connected is False:
            return "degraded"
        return "healthy"


def build_session_health(
    *,
    mode: str,
    strategy_id: str = "default",
    up: bool = True,
    bars_processed: int = 0,
    last_bar_age_seconds: float = 0.0,
    open_orders: int = 0,
    portfolio_value: float | None = None,
    drawdown: float | None = None,
    kill_switch_active: bool = False,
    gateway_connected: bool | None = None,
    notes: list[str] | None = None,
    push_metrics: bool = True,
) -> SessionHealthSnapshot:
    """Create snapshot and optionally push Prometheus gauges."""
    snap = SessionHealthSnapshot(
        mode=str(mode),
        strategy_id=str(strategy_id or "default"),
        up=bool(up),
        bars_processed=int(bars_processed),
        last_bar_age_seconds=float(last_bar_age_seconds),
        open_orders=int(open_orders),
        portfolio_value=portfolio_value,
        drawdown=drawdown,
        kill_switch_active=bool(kill_switch_active),
        gateway_connected=gateway_connected,
        notes=list(notes or []),
        generated_at=datetime.now(UTC).isoformat(),
    )
    if push_metrics:
        update_session_health(
            mode=snap.mode,
            strategy_id=snap.strategy_id,
            up=snap.up and not snap.kill_switch_active,
            bars_processed=snap.bars_processed,
            last_bar_age_seconds=snap.last_bar_age_seconds,
            open_orders=snap.open_orders,
        )
    return snap


def alert_taxonomy_summary() -> dict[str, Any]:
    """Document alert levels, priorities, and sample routing (IMP-05)."""
    samples = [
        (AlertCategory.DRAWDOWN_BREACH, AlertPriority.P0_EMERGENCY),
        (AlertCategory.DATA_STALENESS, AlertPriority.P2_MEDIUM),
        (AlertCategory.SYSTEM_HEALTH, AlertPriority.P3_LOW),
        (AlertCategory.EXECUTION_FAILURE, AlertPriority.P0_EMERGENCY),
        (AlertCategory.SIGNAL_GENERATION, AlertPriority.P3_LOW),
    ]
    routes = []
    for cat, pri in samples:
        routes.append(
            {
                "category": cat.value,
                "priority": pri.value,
                "channels": resolve_alert_channels(cat, pri),
            }
        )
    return {
        "levels": [lvl.value for lvl in AlertLevel],
        "priorities": [p.value for p in AlertPriority],
        "categories": [c.value for c in AlertCategory],
        "sample_routes": routes,
        "routing_matrix_size": len(ALERT_ROUTING),
        "doc": "docs/ops/alert-taxonomy-session-health.md",
    }
