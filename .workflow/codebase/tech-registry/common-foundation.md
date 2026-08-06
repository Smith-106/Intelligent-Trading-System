# TC-007 — CommonFoundation

| Field | Value |
|-------|-------|
| **ID** | TC-007 |
| **Type** | L0-common |
| **Features** |  |
| **Last Updated** | 2026-08-05T05:37:59Z |

## Code Locations

- `quantflow/__init__.py`
- `quantflow/common/models.py`
- `quantflow/common/event_bus.py`
- `quantflow/common/config.py`
- `quantflow/common/validators.py`
- `quantflow/common/exceptions.py`
- `quantflow/common/monitoring_sink.py`
- `quantflow/common/indicator_protocol.py`
- `quantflow/common/schema_exposure.py`
- `quantflow/common/tracing.py`
- `quantflow/common/jsonable.py`
- `quantflow/common/numeric.py`
- `quantflow/common/redaction.py`
- `quantflow/common/url_safety.py`
- `quantflow/common/__init__.py`
- `quantflow/config/__init__.py`

## Exported Symbols

- `AIConfig` — AI layer config model (v0.4.0)
- `AlertChannelConfig`
- `AppConfig`
- `AutoLoopConfigModel` — Auto-trading loop config model (v0.4.0)
- `Bar`
- `COLUMN_PATTERN` — Column validation regex pattern
- `ColumnSchema`
- `ConfigError`
- `CorrelationIdProcessor`
- `DataConfig`
- `DataError`
- `DataNotFoundError`
- `DataValidationError`
- `DatasetSchema`
- `Direction`
- `DynamicBudgetConfig` — Dynamic budget config for RiskEngine (v0.4.0)
- `EVENT_BAR` — Bar event type constant
- `EVENT_FILL` — Fill event type constant (common event bus)
- `EVENT_ORDER` — Order event type constant (common event bus)
- `EVENT_RISK` — Risk event type constant
- `EVENT_SIGNAL` — Signal event type constant
- `EVENT_TICK` — Tick event type constant
- `Event`
- `EventBus`
- `ExchangeHealthConfig` — Exchange health monitor config (v0.4.0)
- `ExecutionConfig`
- `ExecutionError`
- `GatewayConnectionError`
- `IndicatorComputer`
- `IndicatorConfig`
- `KillSwitchActivatedError`
- `MonitoringConfig`
- `MonitoringSink`
- `NullIndicatorComputer`
- `NullMonitoringSink`
- `OTEL_AVAILABLE`
- `Order`
- `OrderError`
- `OrderRequest`
- `OrderResult`
- `OrderSide`
- `OrderStatus`
- `OrderTimeoutError`
- `OrderType`
- `POSITION_EPSILON`
- `Portfolio`
- `PortfolioOptimizationConfig` — Portfolio optimization config (v0.4.0)
- `Position`
- `QuantFlowError`
- `RDAgentConfigModel` — RD-Agent runner config model (v0.4.0)
- `REDACTED_PLACEHOLDER` — Secret redaction placeholder
- `ReconciliationConfig` — Reconciliation engine config (v0.4.0)
- `RiskBreachError`
- `RiskConfig`
- `RiskDecision`
- `RunMode`
- `SENSITIVE_FIELDS` — Sensitive config field names for redaction
- `SYMBOL_PATTERN` — Symbol validation regex pattern
- `SchemaExposure`
- `Signal`
- `SignalError`
- `StateConfig` — Session state store config (v0.4.0)
- `StrategyConfig`
- `StrategyConfigError`
- `StrategyError`
- `TracingContext`
- `UnsafeUrlError`
- `ValidationConfig`
- `clear_correlation_id`
- `create_otel_span`
- `get_correlation_id`
- `get_or_create_correlation_id`
- `init_otel_tracer`
- `load_config`
- `redact_secrets`
- `resolve_config_path`
- `resolve_config_path_safe`
- `safe_number`
- `save_config`
- `series_payload`
- `set_correlation_id`
- `strategy_id_constituents`
- `to_jsonable`
- `traced`
- `validate_columns`
- `validate_outbound_url`
- `validate_quantity`
- `validate_symbol`

## Dependencies

- Upstream: `quantflow/common` (models, exceptions, config).
- Downstream consumers: see feature maps for consumer wiring.

---

*Refreshed by codebase-refresh at 2026-08-05T05:39:39Z*
