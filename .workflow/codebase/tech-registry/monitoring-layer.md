# TC-006 — MonitoringLayer

| Field | Value |
|-------|-------|
| **ID** | TC-006 |
| **Type** | L6-monitoring |
| **Features** | (cross-cutting; not a single FT) |
| **Last Updated** | 2026-08-02T14:30:00Z |

## Code Locations

- `quantflow/monitoring/metrics.py` — Prometheus metrics registry + server
- `quantflow/monitoring/alerts.py` — `AlertManager` (Telegram/LINE/webhook), `AlertCategory` (15 types: system/trading/risk/data/strategy), `AlertPriority` (P0-P3 routing levels)
- `quantflow/monitoring/logger.py` — `setup_logging` (structlog)
- `quantflow/monitoring/sink.py` — `DefaultMonitoringSink`, `create_default_sink`
- `quantflow/monitoring/__init__.py`

## Exported Symbols

`AlertCategory`, `AlertLevel`, `AlertManager`, `AlertPriority`, `DefaultMonitoringSink`, `create_default_sink`,
`metrics_registry_snapshot`, `metrics_server_status`, `setup_logging`, `start_metrics_server`, `update_portfolio_metrics`.

### Alert Taxonomy (G5)

- `AlertCategory`: 15 categories across 5 domains (System/Infrastructure, Trading Operations, Risk Management, Data Quality, Strategy)
- `AlertPriority`: P0_EMERGENCY (immediate page, trading halt) → P1_HIGH (5 min) → P2_MEDIUM (30 min) → P3_LOW (batch, next business day)

## Dependencies

- Upstream: `quantflow/common` (`MonitoringSink` Protocol — injected into L3/L4/L5 to avoid direct `monitoring/` import; arch-013 audit-evasion fix).
- Downstream consumers: L3/L4/L5 emit via `MonitoringSink` Protocol; CLI/Web surface metrics; Prometheus + Grafana + Telegram/LINE for observability.
- External: Prometheus client, structlog, Grafana (deployment).

---

*Refreshed by codebase-refresh at 2026-08-02T14:30:00Z*
