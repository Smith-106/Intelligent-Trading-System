# Tech Registry — Component Index

Auto-generated index of all QuantFlow components. Source of truth: `doc-index.json`.

| ID | Name | Type | Locations |
|----|------|------|-----------|
| TC-001 | DataLayer | L1-data | `quantflow/data/` (8 files) |
| TC-002 | IndicatorsLayer | L2-indicators | `quantflow/indicators/` (16 files) |
| TC-003 | StrategyLayer | L3-strategy | `quantflow/strategy/` (34 files) |
| TC-004 | SignalRiskLayer | L4-signal-risk | `quantflow/signal/` (7 files) |
| TC-005 | ExecutionLayer | L5-execution | `quantflow/execution/` (9 files) |
| TC-006 | MonitoringLayer | L6-monitoring | `quantflow/monitoring/` (5 files) |
| TC-007 | CommonFoundation | L0-common | `quantflow/common/` (15 files) |
| TC-008 | CliEntry | cli | `quantflow/cli/` (4 files) |
| TC-009 | WebStation | web-presentation | `quantflow/web/` (7 files) |
| TC-010 | TradingShim | shim | `quantflow/trading/__init__.py` |
| TC-011 | ReconciliationLayer | L5.5-reconciliation | `quantflow/reconciliation/` (4 files) |

**Component count:** 11 (7 layer components L0–L6, 1 reconciliation L5.5, 1 CLI, 1 Web, 1 shim)

Layer mapping:
- L0 `CommonFoundation` (TC-007) underpins all layers.
- L1 `DataLayer` → L2 `IndicatorsLayer` → L3 `StrategyLayer` → L4 `SignalRiskLayer` → L5 `ExecutionLayer` → L6 `MonitoringLayer` (via `MonitoringSink` Protocol injection).
- L5.5 `ReconciliationLayer` (TC-011) bridges L4 PortfolioManager and L5 Gateway for drift detection.
- Cross-cutting: `CliEntry` (TC-008) and `WebStation` (TC-009) are user-facing entry points; `TradingShim` (TC-010) is a re-export compatibility shim.

---

*Refreshed by codebase-refresh at 2026-08-02T14:30:00Z*
