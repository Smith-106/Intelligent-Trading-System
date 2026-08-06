# TC-006 — MonitoringLayer

| Field | Value |
|-------|-------|
| **ID** | TC-006 |
| **Type** | L6-monitoring |
| **Features** |  |
| **Last Updated** | 2026-08-05T05:37:59Z |

## Code Locations

- `quantflow/monitoring/metrics.py`
- `quantflow/monitoring/alerts.py`
- `quantflow/monitoring/logger.py`
- `quantflow/monitoring/sink.py`
- `quantflow/monitoring/__init__.py`

## Exported Symbols

- `AlertCategory`
- `AlertDeduplicator` — Alert deduplication (v0.3.1 alert routing)
- `AlertLevel`
- `AlertManager`
- `AlertPriority`
- `BAR_PROCESSING_LATENCY` — Prometheus metric name constant
- `DefaultMonitoringSink`
- `GATEWAY_CONNECTED` — Prometheus metric name constant
- `GATEWAY_DISCONNECTS` — Prometheus metric name constant
- `GATEWAY_RECONNECTS` — Prometheus metric name constant
- `KILL_SWITCH_ACTIVATIONS` — Prometheus metric name constant
- `KILL_SWITCH_STEP_FAILURES` — Prometheus metric name constant
- `ORDERS_FILLED` — Prometheus metric name constant
- `ORDERS_TIMED_OUT` — Prometheus metric name constant
- `ORDERS_TOTAL` — Prometheus metric name constant
- `ORDER_LATENCY` — Prometheus metric name constant
- `PORTFOLIO_ALLOCATION` — Prometheus metric name constant
- `PORTFOLIO_CASH` — Prometheus metric name constant
- `PORTFOLIO_DRAWDOWN` — Prometheus metric name constant
- `PORTFOLIO_VALUE` — Prometheus metric name constant
- `POSITIONS_COUNT` — Prometheus metric name constant
- `RISK_EVENTS` — Prometheus metric name constant
- `SIGNALS_GENERATED` — Prometheus metric name constant
- `SIGNAL_PROCESSING_LATENCY` — Prometheus metric name constant
- `STRATEGY_BUDGET_UTILIZATION` — Prometheus metric name constant
- `STRATEGY_PNL` — Prometheus metric name constant
- `create_default_sink`
- `metrics_registry_snapshot`
- `metrics_server_status`
- `resolve_alert_channels` — Resolve alert channel configs per category/level
- `setup_logging`
- `start_metrics_server`
- `update_portfolio_metrics`

## Dependencies

- Upstream: `quantflow/common` (models, exceptions, config).
- Downstream consumers: see feature maps for consumer wiring.

---

*Refreshed by codebase-refresh at 2026-08-05T05:39:39Z*
