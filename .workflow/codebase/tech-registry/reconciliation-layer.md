# TC-011 — ReconciliationLayer

| Field | Value |
|-------|-------|
| **ID** | TC-011 |
| **Type** | L5.5-reconciliation |
| **Features** | FT-012 (Reconciliation Engine) |
| **Last Updated** | 2026-08-05T05:37:59Z |

## Code Locations

- `quantflow/reconciliation/__init__.py`
- `quantflow/reconciliation/engine.py`
- `quantflow/reconciliation/audit_logger.py`
- `quantflow/reconciliation/models.py`

## Exported Symbols

- `AuditLogger`
- `DailyReconReport`
- `Discrepancy`
- `DiscrepancySet`
- `DiscrepancyType` — Discrepancy kind enum (position/order drift)
- `PositionSnapshot`
- `ReconciliationEngine`

## Dependencies

- Upstream: `quantflow/common` (models, exceptions, config).
- Downstream consumers: see feature maps for consumer wiring.

---

*Refreshed by codebase-refresh at 2026-08-05T05:39:39Z*
