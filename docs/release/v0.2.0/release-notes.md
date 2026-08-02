# QuantFlow v0.2.0 Release Notes

**Release Date**: 2026-08-02  
**Tag**: `v0.2.0`  
**Commit**: `fe43aeb`  
**Milestone**: M4 — v0.2 多 Symbol 扩展 + 17 ISS 清零

## Overview

v0.2.0 is a major maintenance and feature release that resolves 17 accumulated issues spanning security hardening, architecture cleanup, and new operational integrity features. This release establishes the foundation for multi-symbol trading and production-grade observability.

## Security Hardening (7 ISS)

- **Rate Limiting**: Per-IP token-bucket middleware on 9 mutating web endpoints (429 + Retry-After)
- **SSRF Protection**: `validate_outbound_url()` with scheme allowlist + loopback/private/link-local IP blocklist
- **Secret Redaction**: Centralized `quantflow/common/redaction.py` (env-literal + bot token/bearer/redis-url shapes)
- **Docker Hardening**: Non-root USER, Redis requirepass, Grafana admin pw via env, no `:latest`, security_opt no-new-privileges, read-only rootfs
- **Session Security**: `session_id=secrets.token_urlsafe(16)` (128-bit), operator_id audit, per-IP session-start throttle
- **CI Hygiene**: SHA-pinned GitHub Actions, `:latest` eliminated, JSONL schema whitelist + size cap
- **Deployment Guardrails**: `.gitignore` private-key/cert patterns, Station host guardrail (loopback default, fail-closed on non-loopback w/o token)

## Architecture Cleanup (6 ISS)

- **ExecutionEngine SRP**: Extracted `OrderRouter` (dispatch + build_order + build_close_request + is_closeable)
- **ScalingPositionSizer**: Dead code removed (zero callers)
- **L6 Protocol Extension**: MonitoringSink expanded to 14 `record_*` + `send_alert` + `start`
- **Three-Book Reconcile**: L4 PortfolioManager single authority, L5 PositionManager thin router delegate, PaperGateway third `_cash` ledger removed
- **PositionSizer Config-Sourced**: `fixed_pct`/`min_order_notional`/`fee_rate` from YAML (byte-for-byte baseline preserved)
- **OKXGateway market_type**: spot/swap dual-branch support

## New Features (4 ISS)

- **IndicatorComputer Protocol**: `common/indicator_protocol.py` — FeatureStore no longer imports from indicators/ (layer violation fix)
- **Recursive Analysis CLI**: `quantflow validate --method recursive` — detects indicator recursive formula errors
- **Benchmark Service**: Extracted from CLI main.py (~400 lines → ~35 line thin shell) into `cli/services/benchmark.py`
- **structlog stdlib Bridge**: `monitoring/logger.py` bridges structlog with stdlib logging

## New Modules (Post-Release Additions)

- **`common/tracing.py`**: Distributed tracing foundation — correlation ID propagation (ContextVar), OpenTelemetry integration (optional), structlog processor injection, `@traced` decorator
- **`data/dq_monitor.py`**: Real-time data quality monitoring — freshness/price-continuity/volume-anomaly detection, composite quality score (0-1), Prometheus metrics, Redis-backed state
- **`reconciliation/`**: Position/order drift detection — ReconciliationEngine (background loop), AuditLogger (HMAC-SHA256 signed), PositionSnapshot/Discrepancy/DailyReconReport models
- **`strategy/factory.py`**: Per-(strategy, symbol) instance creation for multi-symbol isolation

## Multi-Symbol Foundation

- `strategy/factory.py`: `create_per_symbol()` / `create_all_per_symbol()` — isolated strategy instances per symbol
- GatewayBase: `query_open_orders(symbol)` abstract method for orphan order detection
- AlertCategory (15 types) × AlertPriority (4 levels) taxonomy for smart alert routing

## Breaking Changes

None. All changes are backward-compatible. Single-symbol behavior is byte-for-byte unchanged.

## Upgrade Guide

1. `pip install quantflow==0.2.0`
2. No configuration changes required
3. Optional: Enable tracing via `init_otel_tracer()` if OpenTelemetry is installed
4. Optional: Deploy `DataQualityMonitor` for real-time data validation

## Known Issues

- `docs/release/v0.2.0/` release documentation created post-tag (this file)
- 11 harvest-generated issues (ISS-20260802-*) tracked for next iteration
- P2 AI-layer upgrade unblocked but not started

## Test Results

- Full test suite: PASS
- mypy --strict: CLEAN
- ruff check: CLEAN
