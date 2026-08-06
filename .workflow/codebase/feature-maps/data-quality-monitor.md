# FT-011 — Data Quality Monitor

| Field | Value |
|-------|-------|
| **ID** | FT-011 |
| **Status** | active |
| **Phase** | v0.2.0 new feature |

## Requirements

None tracked in `.workflow/blueprint` (no SPEC/REQ files present).

## Components

| Component | Role |
|-----------|------|
| TC-001 (DataLayer) | L1-data — see tech-registry |

## Description

Real-time data quality monitoring (G4): freshness checks (staleness detection), price continuity validation (spike detection), volume anomaly detection. DataQualityMonitor.validate_bar() gates bar publishing. Prometheus metrics (dq_monitor_violations_total, dq_data_staleness_seconds, dq_quality_score). Composite quality score (0-1, weighted: freshness 40% + continuity 30% + anomaly 30%). Redis-backed state.

---

*Refreshed by codebase-refresh at 2026-08-05T05:39:39Z*
