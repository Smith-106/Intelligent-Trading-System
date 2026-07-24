"""Prometheus metrics for QuantFlow monitoring."""

from __future__ import annotations

import logging
import math
from threading import Lock
from typing import Any

from prometheus_client import REGISTRY, Counter, Gauge, Histogram, start_http_server

from quantflow.common.redaction import redact_secrets

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
    """Start Prometheus metrics HTTP server."""
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
                values[counter_key] += value

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
