"""Prometheus metrics for QuantFlow monitoring."""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from threading import Lock
from typing import TYPE_CHECKING, Any

from prometheus_client import REGISTRY, Counter, Gauge, Histogram, start_http_server

from quantflow.common.redaction import redact_secrets

if TYPE_CHECKING:
    from quantflow.monitoring.research_go_panel import ResearchGoPanelSnapshot

logger = logging.getLogger(__name__)
_METRICS_SERVER_LOCK = Lock()
_METRICS_SERVER_STATE: dict[int, dict[str, Any]] = {}

# Counters
ORDERS_TOTAL = Counter(
    "quantflow_orders_total",
    "Total orders submitted",
    ["symbol", "side", "strategy_id"],
)

ORDERS_FILLED = Counter(
    "quantflow_orders_filled_total",
    "Total orders filled",
    ["symbol", "side", "strategy_id"],
)

SIGNALS_GENERATED = Counter(
    "quantflow_signals_generated_total",
    "Total signals generated",
    ["strategy_id", "direction"],
)

RISK_EVENTS = Counter(
    "quantflow_risk_events_total",
    "Total risk events",
    ["event_type", "severity"],
)

# Kill switch (odyssey-improve OBS-H2): every activation — manual web trigger,
# drawdown breach, or emergency alert — increments this so a Grafana panel /
# alert can surface the emergency stop independently of log lines.
KILL_SWITCH_ACTIVATIONS = Counter(
    "quantflow_kill_switch_activations_total",
    "Kill switch activations by trigger reason",
    ["reason"],
)
KILL_SWITCH_STEP_FAILURES = Counter(
    "quantflow_kill_switch_step_failures_total",
    "Kill switch sub-step failures (cancel/close/query) during activation",
    ["step"],
)

# Gateway observability (ISS-20260723-011 OBS-M cluster): liveness gauge +
# disconnect/reconnect/timeout counters so a Grafana panel / alert can surface
# exchange connectivity health independently of log lines. The connected gauge
# is set (not inc) so it reflects the current state, not a cumulative tally.
GATEWAY_CONNECTED = Gauge(
    "quantflow_gateway_connected",
    "Gateway connectivity (1=connected, 0=disconnected) by exchange",
    ["exchange"],
)

GATEWAY_DISCONNECTS = Counter(
    "quantflow_gateway_disconnects_total",
    "Gateway disconnect events by exchange and trigger reason",
    ["exchange", "reason"],
)

GATEWAY_RECONNECTS = Counter(
    "quantflow_gateway_reconnects_total",
    "Gateway reconnect attempts by exchange and outcome (success/failure)",
    ["exchange", "success"],
)

ORDERS_TIMED_OUT = Counter(
    "quantflow_orders_timed_out_total",
    "Orders that exceeded the OrderManager timeout watchdog and were cancelled",
    ["symbol", "side"],
)

# Gauges
PORTFOLIO_VALUE = Gauge(
    "quantflow_portfolio_value",
    "Current portfolio total value",
)

PORTFOLIO_CASH = Gauge(
    "quantflow_portfolio_cash",
    "Current cash balance",
)

PORTFOLIO_DRAWDOWN = Gauge(
    "quantflow_portfolio_drawdown",
    "Current portfolio drawdown",
)

POSITIONS_COUNT = Gauge(
    "quantflow_positions_count",
    "Number of open positions",
)

# IMP-05: TradingSession / paper-live health (exportable snapshot + gauges).
SESSION_HEALTH_UP = Gauge(
    "quantflow_session_health_up",
    "Session liveness (1=healthy/running, 0=stopped/degraded)",
    ["mode", "strategy_id"],
)
SESSION_BARS_PROCESSED = Gauge(
    "quantflow_session_bars_processed",
    "Bars processed in the active session",
    ["mode", "strategy_id"],
)
SESSION_LAST_BAR_AGE_SECONDS = Gauge(
    "quantflow_session_last_bar_age_seconds",
    "Seconds since last bar handled (staleness)",
    ["mode", "strategy_id"],
)
SESSION_OPEN_ORDERS = Gauge(
    "quantflow_session_open_orders",
    "Open orders tracked by the active session",
    ["mode", "strategy_id"],
)

# s4 (T-s4-05): strategy-level PnL split (realized + unrealized attribution)
# and budget utilization. Fed by MonitoringSink.record_strategy_pnl; strategy
# granularity matches the strategy_id labels already on signal/order metrics.
STRATEGY_PNL = Gauge(
    "quantflow_strategy_pnl",
    "Cumulative PnL by strategy (realized + unrealized attribution)",
    ["strategy_id"],
)

STRATEGY_BUDGET_UTILIZATION = Gauge(
    "quantflow_strategy_budget_utilization",
    "Strategy budget utilization fraction (exposure / budget limit)",
    ["strategy_id"],
)

# s5 follow-up: portfolio-level allocation weights (risk-parity / min-variance).
# Fed by MonitoringSink.record_portfolio_allocation after each rebalance.
PORTFOLIO_ALLOCATION = Gauge(
    "quantflow_portfolio_allocation",
    "Portfolio allocation weight by strategy (rebalanced)",
    ["strategy_id"],
)

# L6 research GO export (deferred observability gap): sealed panel fields
# surfaced as gauges for ops dashboards. Fed by
# update_research_go_panel_metrics / MonitoringSink.record_research_go_panel
# (off hot path — never called from on_bar). Fingerprint + decision +
# primary_mode ride as labels on the decision/value gauges; path_semantics
# narrative keys stay in the JSON snapshot export only (no dedicated gauges).
RESEARCH_GO_DECISION = Gauge(
    "quantflow_research_go_decision",
    "Sealed research GO gate decision (1=PAPER-GO, 0=other)",
    ["primary_mode", "decision", "fingerprint", "promotion_eligible"],
)

RESEARCH_GO_RETURN_PCT = Gauge(
    "quantflow_research_go_return_pct",
    "Sealed research GO full-window return % (primary mode)",
    ["primary_mode", "decision", "fingerprint", "promotion_eligible"],
)

RESEARCH_GO_SHARPE = Gauge(
    "quantflow_research_go_sharpe",
    "Sealed research GO full-window Sharpe (primary mode)",
    ["primary_mode", "decision", "fingerprint", "promotion_eligible"],
)

RESEARCH_GO_MAX_DD_PCT = Gauge(
    "quantflow_research_go_max_dd_pct",
    "Sealed research GO full-window max drawdown % (primary mode)",
    ["primary_mode", "decision", "fingerprint", "promotion_eligible"],
)

RESEARCH_GO_ORDERS = Gauge(
    "quantflow_research_go_orders",
    "Sealed research GO full-window order count (primary mode)",
    ["primary_mode", "decision", "fingerprint", "promotion_eligible"],
)

RESEARCH_GO_PROMOTION_ELIGIBLE = Gauge(
    "quantflow_research_go_promotion_eligible",
    "Research GO promotion eligibility (always 0 — export never promotes)",
    ["primary_mode", "decision", "fingerprint", "promotion_eligible"],
)

RESEARCH_GO_AS_OF_TS = Gauge(
    "quantflow_research_go_as_of_timestamp",
    "Sealed research GO panel as-of timestamp (unix seconds)",
)

# Histograms
ORDER_LATENCY = Histogram(
    "quantflow_order_latency_seconds",
    "Order submission latency",
    ["symbol"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

BAR_PROCESSING_LATENCY = Histogram(
    "quantflow_bar_processing_latency_seconds",
    "End-to-end TradingSession.on_bar processing latency",
    ["symbol"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

SIGNAL_PROCESSING_LATENCY = Histogram(
    "quantflow_signal_processing_latency_seconds",
    "Signal risk, sizing, and execution pipeline latency",
    ["strategy_id"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)


def start_metrics_server(port: int = 9090) -> None:
    """Start Prometheus metrics HTTP server (idempotent per port).

    A repeated call on a port that already started is a no-op rather than
    raising "address in use" — callers (e.g. TradingSession.start across
    restarts, sink.start) can invoke this without tracking their own
    attempt set. The per-port state under ``_METRICS_SERVER_STATE`` makes
    the decision; ``state["started"]`` True means the server is live.
    """
    with _METRICS_SERVER_LOCK:
        state = _METRICS_SERVER_STATE.setdefault(
            int(port),
            {
                "port": int(port),
                "attempted": False,
                "started": False,
                "last_error": None,
            },
        )
        # Idempotent: already started (or already attempted and failed) on this
        # port — do not call start_http_server again, which would raise
        # "address in use" on a live port and overwrite last_error.
        if state["attempted"]:
            return
        state["attempted"] = True
    try:
        start_http_server(port)
        with _METRICS_SERVER_LOCK:
            state["started"] = True
            state["last_error"] = None
        logger.info("Prometheus metrics server started on port %d", port)
    except Exception as e:
        with _METRICS_SERVER_LOCK:
            state["started"] = False
            # ISS-035 (SEC, CWE-209): metrics_server_status() is surfaced via
            # web/service.py → HTTP response. A start failure (e.g. a redis://
            # URL or infra credential in the bind error) must be scrubbed before
            # it reaches state["last_error"] AND the log.
            state["last_error"] = redact_secrets(str(e))
        logger.warning("Failed to start metrics server: %s", redact_secrets(str(e)))


def metrics_server_status(port: int | None = None) -> dict[str, Any]:
    """Return the last known metrics-server startup status for a port."""
    if port is None:
        return {
            "port": None,
            "attempted": False,
            "started": False,
            "last_error": None,
        }
    with _METRICS_SERVER_LOCK:
        state = _METRICS_SERVER_STATE.get(int(port))
        if state is None:
            return {
                "port": int(port),
                "attempted": False,
                "started": False,
                "last_error": None,
            }
        return dict(state)


def metrics_registry_snapshot() -> dict[str, Any]:
    """Return a compact snapshot of the in-process Prometheus registry."""
    values = {
        "portfolio_value": None,
        "portfolio_cash": None,
        "portfolio_drawdown": None,
        "positions_count": None,
        "orders_total": 0.0,
        "orders_filled_total": 0.0,
        "signals_generated_total": 0.0,
        "risk_events_total": 0.0,
        "order_latency_count": 0.0,
        "order_latency_sum": 0.0,
        "bar_latency_count": 0.0,
        "bar_latency_sum": 0.0,
        "signal_latency_count": 0.0,
        "signal_latency_sum": 0.0,
    }
    scalar_map = {
        "quantflow_portfolio_value": "portfolio_value",
        "quantflow_portfolio_cash": "portfolio_cash",
        "quantflow_portfolio_drawdown": "portfolio_drawdown",
        "quantflow_positions_count": "positions_count",
    }
    counter_map = {
        "quantflow_orders_total": "orders_total",
        "quantflow_orders_filled_total": "orders_filled_total",
        "quantflow_signals_generated_total": "signals_generated_total",
        "quantflow_risk_events_total": "risk_events_total",
        "quantflow_order_latency_seconds_count": "order_latency_count",
        "quantflow_order_latency_seconds_sum": "order_latency_sum",
        "quantflow_bar_processing_latency_seconds_count": "bar_latency_count",
        "quantflow_bar_processing_latency_seconds_sum": "bar_latency_sum",
        "quantflow_signal_processing_latency_seconds_count": "signal_latency_count",
        "quantflow_signal_processing_latency_seconds_sum": "signal_latency_sum",
    }

    for family in REGISTRY.collect():
        for sample in family.samples:
            value = float(sample.value)
            if not math.isfinite(value):
                continue
            scalar_key = scalar_map.get(sample.name)
            if scalar_key:
                values[scalar_key] = value
                continue
            counter_key = counter_map.get(sample.name)
            if counter_key:
                # counter_key is a str (truthy); values[counter_key] is a float
                # (counter_map only maps to counter keys, all initialized to 0.0,
                # never the positions_count None placeholder). Assert to narrow
                # for mypy — the dict's declared value type is float | None.
                current = values[counter_key]
                assert current is not None
                values[counter_key] = current + value

    return {
        "available": True,
        "values": {
            key: int(value)
            if isinstance(value, float) and value.is_integer() and key.endswith("_count")
            else int(value)
            if isinstance(value, float) and value.is_integer() and key.endswith("_total")
            else value
            for key, value in values.items()
        },
    }


def update_research_go_panel_metrics(
    snapshot: ResearchGoPanelSnapshot | None,
) -> None:
    """Push sealed research GO panel fields into quantflow_research_go_* gauges.

    Fail-soft: ``None`` is a no-op; malformed as_of is skipped (debug log)
    rather than raised. ``promotion_eligible`` is forced to 0.0 — research
    GO export is never a live-promotion signal (locks.no_live_promote).
    """
    if snapshot is None:
        return
    labels = {
        "primary_mode": snapshot.primary_mode,
        "decision": snapshot.decision,
        "fingerprint": snapshot.data_fingerprint_aggregate,
        "promotion_eligible": "false",
    }
    decision_value = 1.0 if snapshot.decision == "PAPER-GO" else 0.0
    RESEARCH_GO_DECISION.labels(**labels).set(decision_value)
    RESEARCH_GO_RETURN_PCT.labels(**labels).set(float(snapshot.full_return_pct))
    RESEARCH_GO_SHARPE.labels(**labels).set(float(snapshot.full_sharpe))
    RESEARCH_GO_MAX_DD_PCT.labels(**labels).set(float(snapshot.full_max_dd_pct))
    RESEARCH_GO_ORDERS.labels(**labels).set(float(snapshot.full_orders))
    RESEARCH_GO_PROMOTION_ELIGIBLE.labels(**labels).set(0.0)
    if snapshot.as_of:
        try:
            ts = datetime.fromisoformat(snapshot.as_of)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            RESEARCH_GO_AS_OF_TS.set(ts.timestamp())
        except ValueError:
            logger.debug(
                "research GO panel as_of %r not parseable — gauge skipped",
                snapshot.as_of,
            )


def update_portfolio_metrics(
    total_value: float,
    cash: float,
    drawdown: float,
    n_positions: int,
) -> None:
    """Update portfolio-related Prometheus gauges."""
    PORTFOLIO_VALUE.set(total_value)
    PORTFOLIO_CASH.set(cash)
    PORTFOLIO_DRAWDOWN.set(drawdown)
    POSITIONS_COUNT.set(n_positions)


def update_session_health(
    *,
    mode: str,
    strategy_id: str = "default",
    up: bool = True,
    bars_processed: int = 0,
    last_bar_age_seconds: float = 0.0,
    open_orders: int = 0,
) -> None:
    """Update IMP-05 session health gauges (paper/live/backtest modes)."""
    m = str(mode or "unknown")
    sid = str(strategy_id or "default")
    SESSION_HEALTH_UP.labels(mode=m, strategy_id=sid).set(1.0 if up else 0.0)
    SESSION_BARS_PROCESSED.labels(mode=m, strategy_id=sid).set(float(bars_processed))
    SESSION_LAST_BAR_AGE_SECONDS.labels(mode=m, strategy_id=sid).set(float(last_bar_age_seconds))
    SESSION_OPEN_ORDERS.labels(mode=m, strategy_id=sid).set(float(open_orders))
