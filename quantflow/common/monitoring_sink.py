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

    def record_risk_event(self, event_type: str, severity: str) -> None:
        """Increment the risk-events counter for (event_type, severity).

        Used by L4 RiskEngine — the L4→L6 seam (ISS-20260724-044) that
        replaced ``risk_engine``'s in-function ``RISK_EVENTS`` import.
        """
        ...

    def record_kill_switch_activation(self, reason: str) -> None:
        """Increment the kill-switch-activations counter for ``reason``.

        Used by L5 KillSwitch — replaced the top-level
        ``KILL_SWITCH_ACTIVATIONS`` import (ISS-20260724-044).
        """
        ...

    def record_kill_switch_step_failure(self, step: str) -> None:
        """Increment the kill-switch-step-failures counter for ``step``.

        Used by L5 KillSwitch for each failed emergency-stop step (cancel /
        query / close) — replaced ``KILL_SWITCH_STEP_FAILURES`` import.
        """
        ...

    def record_order_total(self, symbol: str, side: str, strategy_id: str) -> None:
        """Increment the orders-total counter (every submitted/rejected order).

        Used by L5 ExecutionEngine — replaced ``ORDERS_TOTAL`` import.
        """
        ...

    def record_order_filled(self, symbol: str, side: str, strategy_id: str) -> None:
        """Increment the orders-filled counter (orders that reached FILLED).

        Used by L5 ExecutionEngine — replaced ``ORDERS_FILLED`` import.
        """
        ...

    def record_order_latency(self, symbol: str, duration_seconds: float) -> None:
        """Observe order-submission latency for ``symbol``.

        Used by L5 ExecutionEngine — replaced ``ORDER_LATENCY`` import.
        """
        ...

    def record_gateway_connected(self, exchange: str, connected: bool) -> None:
        """Set the gateway connectivity gauge for ``exchange`` (1/0).

        ISS-20260723-011 (OBS-M): used by L5 OKXGateway at connect/disconnect
        and on connection-loss branches in send_order/query_positions so a
        Grafana panel surfaces liveness independently of log lines. ``set``
        semantics — reflects current state, not a cumulative tally.
        """
        ...

    def record_gateway_disconnect(self, exchange: str, reason: str) -> None:
        """Increment the gateway-disconnect counter for (exchange, reason).

        ISS-20260723-011 (OBS-M): used by L5 OKXGateway on every disconnect
        path (timeout, exception, explicit disconnect). ``reason`` is a
        short label (``timeout`` / ``error`` / ``shutdown``).
        """
        ...

    def record_gateway_reconnect(self, exchange: str, success: bool) -> None:
        """Increment the gateway-reconnect counter for (exchange, success).

        ISS-20260723-011 (OBS-M): used by L5 OKXGateway.ensure_connected per
        reconnect attempt so alerting can distinguish repeated reconnect
        failures (``success=False``) from healthy recovery.
        """
        ...

    def record_order_timed_out(self, symbol: str, side: str) -> None:
        """Increment the orders-timed-out counter for (symbol, side).

        ISS-20260723-011 (OBS-M): used by L5 OrderManager.check_timeouts when
        an order exceeds the watchdog window and is marked CANCELLED. Lets a
        panel/alert surface stale-order churn without log mining.
        """
        ...

    def record_strategy_pnl(self, strategy_id: str, pnl: float, budget_utilization: float | None = None) -> None:
        """s4 (T-s4-05): push strategy-level PnL + budget utilization.

        Used by L4/TradingSession for the strategy-factory monitoring split
        (strategy PnL attribution, budget utilization panel).
        """
        ...

    def record_portfolio_allocation(self, weights: dict[str, float]) -> None:
        """s5 follow-up: push rebalanced portfolio allocation weights.

        Used by TradingSession after each risk-parity / min-variance
        rebalance so the allocation is observable (per-strategy gauge).
        Best-effort like every sink method — must never raise.
        """
        ...

    def record_research_go_panel(self, snapshot: Any) -> None:
        """Best-effort push of the sealed research GO panel snapshot.

        L6 research GO export (off hot path): ``snapshot`` is a
        ``ResearchGoPanelSnapshot``-shaped object (kept ``Any`` here so the
        L3/L4 seam stays free of L6 imports) or None. Implementations no-op
        on None and never raise — missing/invalid panels are fail-soft.
        """
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

    def record_risk_event(self, event_type: str, severity: str) -> None:
        """No-op."""

    def record_kill_switch_activation(self, reason: str) -> None:
        """No-op."""

    def record_kill_switch_step_failure(self, step: str) -> None:
        """No-op."""

    def record_order_total(self, symbol: str, side: str, strategy_id: str) -> None:
        """No-op."""

    def record_order_filled(self, symbol: str, side: str, strategy_id: str) -> None:
        """No-op."""

    def record_order_latency(self, symbol: str, duration_seconds: float) -> None:
        """No-op."""

    def record_gateway_connected(self, exchange: str, connected: bool) -> None:
        """No-op."""

    def record_gateway_disconnect(self, exchange: str, reason: str) -> None:
        """No-op."""

    def record_gateway_reconnect(self, exchange: str, success: bool) -> None:
        """No-op."""

    def record_order_timed_out(self, symbol: str, side: str) -> None:
        """No-op."""

    def record_strategy_pnl(self, strategy_id: str, pnl: float, budget_utilization: float | None = None) -> None:
        """No-op."""

    def record_portfolio_allocation(self, weights: dict[str, float]) -> None:
        """No-op."""

    def record_research_go_panel(self, snapshot: Any) -> None:
        """No-op — research GO gauges are not pushed by the null sink."""

    async def send_alert(
        self,
        message: str,
        level: str = "warning",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, bool]:
        """No-op — returns empty dict (no channels configured)."""
        return {}
