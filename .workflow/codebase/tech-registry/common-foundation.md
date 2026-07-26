# TC-007 — CommonFoundation

| Field | Value |
|-------|-------|
| **ID** | TC-007 |
| **Type** | L0-common |
| **Features** | (foundation — imported by every layer) |

## Code Locations

- `quantflow/common/models.py:10-167` — Enums (`Direction`, `OrderSide`, `OrderType`, `OrderStatus`, `RunMode`), 6 event constants (`EVENT_BAR`..`EVENT_RISK` at L47-52), dataclasses (`Bar`, `Signal`, `Position`, `OrderRequest`, `Order`, `OrderResult`, `Portfolio`, `RiskDecision`), `strategy_id_constituents()` (L76, compound-key splitter)
- `quantflow/common/event_bus.py:36-117` — `Event` (slotted immutable), `EventBus` (`subscribe`/`publish`/`publish_async`; sync + async handlers; exceptions caught+logged to prevent cascade L96-97)
- `quantflow/common/config.py:93-99` — `AppConfig` (Pydantic) aggregating `DataConfig`, `IndicatorConfig`, `StrategyConfig`, `RiskConfig`, `ExecutionConfig`, `MonitoringConfig`. `load_config` (L164): CLI > env (`QUANTFLOW_` prefix L188) > YAML. `resolve_config_path_safe` (L132) blocks path traversal. `SENSITIVE_FIELDS` sanitize (L243), `save_config` defaults `sanitize=True` (L268)
- `quantflow/common/validators.py:21-56` — **Public security choke point**: `validate_symbol` (L28, `/`→`_` SQL/fs-safe form), `validate_columns` (L47), `SYMBOL_PATTERN=^[A-Za-z0-9/_-]{1,20}$` (L21), `COLUMN_PATTERN=^[A-Za-z_][A-Za-z0-9_]*$` (L25)
- `quantflow/common/exceptions.py:4-62` — `QuantFlowError` root; per-layer families: `DataError`/`DataNotFoundError`/`DataValidationError`, `StrategyError`/`StrategyConfigError`, `SignalError`/`RiskBreachError`/`KillSwitchActivatedError`, `ExecutionError`/`OrderError`/`OrderTimeoutError`/`GatewayConnectionError`, `ConfigError`
- `quantflow/common/monitoring_sink.py` — **ISS-019 L6 解耦 seam**: `MonitoringSink` (`@runtime_checkable` Protocol, 12 methods: start/record_signal/record_bar_latency/record_signal_latency/record_portfolio/record_risk_event/record_kill_switch_*/record_order_*/send_alert) + `NullMonitoringSink` (zero-cost no-op default, used by backtest/tests). Lower layers depend on this Protocol instead of importing `quantflow.monitoring.*`.
- `quantflow/common/jsonable.py` — **ISS-041 single-owner serialization**: `to_jsonable()` (single source of truth for JSON-safe conversion, eliminates pandas/numpy type leakage across web + history). `web/service.py` and `web/history.py` both route through it.
- `quantflow/common/numeric.py` — `safe_number()` (JSON-safe numeric coercion, single source; replaces scattered `_safe_number` impls). `web/session_manager.py` consumes it.
- `quantflow/common/redaction.py` — `redact_secrets()` (cross-cutting secret masking; `OKX_API_KEY`/`OKX_SECRET`/`OKX_PASSPHRASE` → `***REDACTED***`). Consolidates `_redact_secrets` logic.
- `quantflow/common/url_safety.py` — `validate_outbound_url()` (SSRF prevention choke point; raises `UnsafeUrlError`). Guards webhook/alert egress + station data-source tagging.

## Exported Symbols

`AlertChannelConfig`, `AppConfig`, `Bar`, `ConfigError`, `DataConfig`, `DataError`, `DataNotFoundError`, `DataValidationError`, `Direction`, `Event`, `EventBus`, `ExecutionConfig`, `ExecutionError`, `GatewayConnectionError`, `IndicatorConfig`, `KillSwitchActivatedError`, `MonitoringConfig`, `MonitoringSink`, `NullMonitoringSink`, `Order`, `OrderError`, `OrderRequest`, `OrderResult`, `OrderSide`, `OrderStatus`, `OrderTimeoutError`, `OrderType`, `Portfolio`, `Position`, `QuantFlowError`, `RiskBreachError`, `RiskConfig`, `RiskDecision`, `RunMode`, `Signal`, `SignalError`, `StrategyConfig`, `StrategyConfigError`, `StrategyError`, `UnsafeUrlError`, `ValidationConfig`, `load_config`, `redact_secrets`, `resolve_config_path`, `resolve_config_path_safe`, `safe_number`, `save_config`, `series_payload`, `strategy_id_constituents`, `to_jsonable`, `validate_columns`, `validate_outbound_url`, `validate_quantity`, `validate_symbol`

## Dependencies

- **Imports**: stdlib + pydantic only. Root of dependency graph — no upward deps.
- **Imported by**: every other layer.

## Notes

- **6 core event types** (the "6种核心事件类型"): `bar`, `tick`, `signal`, `order`, `fill`, `risk` — constants in `models.py:47-52`, re-exported by `event_bus.py:24-33`.
- **Public security primitives**: `validators.py` symbols are explicitly public (no underscore) per REV-005 spec — closes SQL-injection (CWE-89 via glob) + path-traversal (CWE-22). Imported by `data/store`, `data/fetcher`, `data/feature_store`, `web/service`. `data/store.py:16-36` keeps underscored `_validate_symbol`/`_validate_columns` back-compat aliases (only kept while tests import underscored form).
- **Config layering**: YAML → `QUANTFLOW_` env (`__` nested) → CLI deep-merge (`load_config` L164-185).
- **YAML-schema-drift fix**: `RiskConfig.kelly_fraction` (L64) + `var_confidence` (L68) now loaded from YAML (previously hardcoded in TradingSession/risk_engine — silent-drop anti-pattern).
- **ISS-019 L6 解耦 seam (new)**: `monitoring_sink.py` defines the `MonitoringSink` Protocol + `NullMonitoringSink` no-op default. Lower layers (L3 `strategy/engine`, L4 `signal/risk_engine`, L5 `execution/engine`+`kill_switch`) take `monitoring_sink: MonitoringSink | None = None` and default to `NullMonitoringSink`, eliminating direct `quantflow.monitoring.*` imports (closes arch-013 audit-evasion lazy-import). The L6 impl `monitoring/sink.py` `DefaultMonitoringSink` is injected by high-level callers only.
- **ISS-041 single-owner serialization (new)**: `jsonable.py` `to_jsonable()` + `numeric.py` `safe_number()` + `redaction.py` `redact_secrets()` + `url_safety.py` `validate_outbound_url()` consolidate cross-cutting web concerns that were previously duplicated across `web/service.py`, `web/history.py`, `web/session_manager.py`. Single-owner pattern eliminates the pandas-type-leakage + redaction-logic-drift anti-patterns.

*Auto-generated by codebase-refresh at 2026-07-25T00:00:00Z*
