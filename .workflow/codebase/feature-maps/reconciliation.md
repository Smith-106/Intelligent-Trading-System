# FT-012 — Reconciliation Engine

| Field | Value |
|-------|-------|
| **ID** | FT-012 |
| **Status** | active |
| **Phase** | v0.2.0 new feature |

## Requirements

None tracked in `.workflow/blueprint` (no SPEC/REQ files present).

## Components

| Component | Role |
|-----------|------|
| TC-011 (ReconciliationLayer) | L5.5-reconciliation — see tech-registry |

## Description

Position/order drift detection and resolution (ISS-20260720-004): ReconciliationEngine with background reconciliation loop, AuditLogger with HMAC-signed audit trail for compliance, PositionSnapshot/Discrepancy/DiscrepancySet/DailyReconReport models. Detects L4 PortfolioManager vs gateway position drift.

---

*Refreshed by codebase-refresh at 2026-08-05T05:39:39Z*
