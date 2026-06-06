"""Prometheus metrics for QuantFlow monitoring."""

from __future__ import annotations

import logging

from prometheus_client import Counter, Gauge, Histogram, start_http_server

logger = logging.getLogger(__name__)

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
    try:
        start_http_server(port)
        logger.info("Prometheus metrics server started on port %d", port)
    except Exception as e:
        logger.warning("Failed to start metrics server: %s", e)


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
