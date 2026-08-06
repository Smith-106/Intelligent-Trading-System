# FT-007 — Data Layer

| Field | Value |
|-------|-------|
| **ID** | FT-007 |
| **Status** | active |
| **Phase** | Phase 1 complete (P0 leak-safe hardening code-complete-await-verify) |

## Requirements

None tracked in `.workflow/blueprint` (no SPEC/REQ files present).

## Components

| Component | Role |
|-----------|------|
| TC-001 (DataLayer) | L1-data — see tech-registry |

## Description

CCXT async OKX fetcher (REST+WebSocket), Parquet Hive-partitioned storage (symbol/year/month) + DuckDB zero-copy query (path-traversal + SQL-injection guards), FeatureStore point-in-time safe (no future leak), RedisCache real-time ticker, MTFAligner multi-timeframe (leak-safe HTF shift). clean_ohlcv + validate_no_future_leak.

---

*Refreshed by codebase-refresh at 2026-08-05T05:39:39Z*
