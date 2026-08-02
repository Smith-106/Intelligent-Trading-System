# TC-011 — ReconciliationLayer

| Field | Value |
|-------|-------|
| **ID** | TC-011 |
| **Type** | L5.5-reconciliation |
| **Features** | FT-012 (Reconciliation Engine) |
| **Last Updated** | 2026-08-02T14:30:00Z |

## Code Locations

- `quantflow/reconciliation/__init__.py` — public API re-exports
- `quantflow/reconciliation/engine.py` — `ReconciliationEngine` (background reconciliation loop, drift detection, discrepancy classification)
- `quantflow/reconciliation/audit_logger.py` — `AuditLogger` (HMAC-SHA256 signed audit trail, canonical message format, constant-time verification, daily JSONL rotation)
- `quantflow/reconciliation/models.py` — `PositionSnapshot`, `Discrepancy`, `DiscrepancySet`, `DailyReconReport`

## Exported Symbols

`ReconciliationEngine`, `AuditLogger`, `PositionSnapshot`, `Discrepancy`, `DiscrepancySet`, `DailyReconReport`.

## Architecture

```
L4 PortfolioManager (authority)
        ↓ snapshot
ReconciliationEngine.compare()
        ↓ vs
L5 GatewayBase.query_positions() + query_open_orders()
        ↓
DiscrepancySet (POSITION_MISMATCH | ORPHAN_ORDER | ORDER_MISMATCH)
        ↓
AuditLogger.log_event() (HMAC-SHA256 signed)
        ↓
AlertManager (RECONCILIATION_DRIFT category, P0/P1 priority)
```

## Key Behaviors

- **Background loop**: Configurable interval (default 5 min), drift threshold (<1% default, basis points)
- **Discrepancy types**: POSITION_MISMATCH, ORPHAN_ORDER_LOCAL, ORPHAN_ORDER_EXCHANGE, ORDER_MISMATCH
- **Audit trail**: HMAC-SHA256 tamper-evident logging, canonical JSON (sorted keys), constant-time signature comparison
- **Daily report**: `DailyReconReport` with aggregate metrics (total_discrepancies, max_severity, total_value_at_risk)

## Dependencies

- Upstream: `quantflow/signal` (`PortfolioManager`), `quantflow/execution` (`GatewayBase`, `OpenOrder`), `quantflow/common` (models).
- Downstream consumers: `quantflow/monitoring` (`AlertManager` via `RECONCILIATION_DRIFT` category).
- External: Redis (optional state persistence).
- Security: HMAC secret key for audit signing; audit logs are append-only.

## Origin

ISS-20260720-004: Reconciliation mechanism acknowledged but never implemented since project inception. Identified as CRITICAL gap by team-swarm exploration (TS-quantflow-improvements-20260801, confidence 0.95). Implemented as G2 operational integrity feature.

---

*Created by codebase-refresh at 2026-08-02T14:30:00Z*
