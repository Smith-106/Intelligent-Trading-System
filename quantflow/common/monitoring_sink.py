"""Monitoring sink — L3/L4/L5 seam for L6 observability (ISS-019).

Lower layers (TradingSession in L3, ExecutionEngine in L5) need to push
observations (signals generated, bar latency, portfolio snapshot) and emit
alerts. Importing ``monitoring/`` (L6) concrete classes directly from L3/L5
violates the event-driven layering contract — L6 should subscribe to the
EventBus and be injected, not imported by lower layers (see
architecture-constraints-013: L6 cross-layer coupling, and the lazy-import
audit-evasion anti-pattern).

This module defines the :class:`MonitoringSink` Protocol (the contract lower
layers depend on) and :class:`NullMonitoringSink` (a safe no-op default so a
TradingSession can run with zero observability, e.g. in tests/backtest). The
real implementation lives in ``quantflow/monitoring/sink.py`` (L6 owns L6
logic) and is injected by the caller (cli / session_manager), never imported
by lower layers.

Why a Protocol and not EventBus-only: the existing EventBus already carries
BAR/SIGNAL/RISK/ORDER/FILL events for *control* flow. Metrics push and alert
send are *observability side-effects* — adding 3+ new event types purely for
telemetry would inflate the event contract and force every consumer to filter
them. A dedicated sink Protocol keeps the seam explicit and the EventBus
focused on control flow (learnings-001: a cross-layer contract is a public API
with a single audit surface).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MonitoringSink(Protocol):
    """Observability seam lower layers use instead of importing monitoring/.

    All methods are best-effort — a sink MUST NOT raise into the caller's
    hot path (per-bar loop, order submission). Implementations swallow internal
    errors and log them, matching the existing metrics/alerts posture.
    """

    def start(self, config: Any) -> None:
        """Initialize the sink (start metrics server, wire alert channels).

        Called once at session start. ``config`` is the AppConfig; the sink
        reads ``config.monitoring`` (alert_channels, prometheus_port).
        """
        ...

    def record_signal(self, strategy_id: str, direction: str) -> None:
        """Increment the signals-generated counter for (strategy, direction)."""
        ...

    def record_bar_latency(self, symbol: str, duration_seconds: float) -> None:
        """Observe bar-processing latency for ``symbol``."""
        ...

    def record_signal_latency(self, strategy_id: str, duration_seconds: float) -> None:
        """Observe signal-processing latency for ``strategy_id``."""
        ...

    def record_portfolio(
        self,
        total_value: float,
        cash: float,
        drawdown: float,
        n_positions: int,
    ) -> None:
        """Push a portfolio snapshot (value/cash/drawdown/positions) to metrics."""
        ...

    async def send_alert(
        self,
        message: str,
        level: str = "warning",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, bool]:
        """Emit an alert on configured channels. Returns per-channel success.

        ``level`` is a plain string ("info"|"warning"|"critical") so this
        contract does not depend on monitoring.alerts.AlertLevel.
        """
        ...


class NullMonitoringSink:
    """No-op sink — the default when none is injected.

    Used by tests and backtest runs that want zero observability overhead and
    zero L6 coupling. Every method is a cheap no-op so callers need not
    null-check the sink.
    """

    def start(self, config: Any) -> None:
        """No-op — no metrics server, no alert channels."""

    def record_signal(self, strategy_id: str, direction: str) -> None:
        """No-op."""

    def record_bar_latency(self, symbol: str, duration_seconds: float) -> None:
        """No-op."""

    def record_signal_latency(self, strategy_id: str, duration_seconds: float) -> None:
        """No-op."""

    def record_portfolio(
        self,
        total_value: float,
        cash: float,
        drawdown: float,
        n_positions: int,
    ) -> None:
        """No-op."""

    async def send_alert(
        self,
        message: str,
        level: str = "warning",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, bool]:
        """No-op — returns empty dict (no channels configured)."""
        return {}
