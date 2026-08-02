# TC-007 — CommonFoundation

| Field | Value |
|-------|-------|
| **ID** | TC-007 |
| **Type** | L0-common |
| **Features** | (cross-cutting foundation) |
| **Last Updated** | 2026-08-02T14:30:00Z |

## Code Locations

- `quantflow/common/models.py` — data models (`Bar`, `Order`, `Position`, `Portfolio`, `Signal`, `OrderRequest`, `PositionRequest`, etc.)
- `quantflow/common/event_bus.py` — `EventBus` (6 core event types)
- `quantflow/common/config.py` — `AppConfig`, `load_config`, `save_config`, `resolve_config_path_safe`
- `quantflow/common/validators.py` — `validate_symbol`, `validate_quantity`, `validate_columns`
- `quantflow/common/exceptions.py` — `QuantFlowError` hierarchy
- `quantflow/common/monitoring_sink.py` — `MonitoringSink` Protocol, `NullMonitoringSink`
- `quantflow/common/jsonable.py` — `to_jsonable`, `series_payload`
- `quantflow/common/numeric.py` — `safe_number`
- `quantflow/common/redaction.py` — `redact_secrets`
- `quantflow/common/url_safety.py` — `validate_outbound_url`, `UnsafeUrlError`
- `quantflow/common/tracing.py` — `get_correlation_id`, `set_correlation_id`, `get_or_create_correlation_id`, `clear_correlation_id`, `traced` (decorator), `CorrelationIdProcessor` (structlog), `TracingContext` (async CM), `init_otel_tracer`, `create_otel_span`, `OTEL_AVAILABLE`
- `quantflow/common/indicator_protocol.py` — `IndicatorComputer` Protocol, `NullIndicatorComputer`
- `quantflow/common/schema_exposure.py` — `SchemaExposure`, `DatasetSchema`, `ColumnSchema`
- `quantflow/common/__init__.py`

## Exported Symbols (selected)

`AppConfig`, `Bar`, `Event`, `EventBus`, `Order`, `OrderRequest`, `OrderResult`, `Position`, `Portfolio`,
`PositionRequest`, `Signal`, `RunMode`, `Direction`, `OrderSide`, `OrderType`, `OrderStatus`,
`MonitoringSink`, `NullMonitoringSink`, `QuantFlowError`, `DataError`, `StrategyError`, `RiskBreachError`,
`OrderError`, `GatewayConnectionError`, `KillSwitchActivatedError`, `UnsafeUrlError`, `load_config`, `save_config`,
`resolve_config_path`, `resolve_config_path_safe`, `redact_secrets`, `validate_outbound_url`, `validate_symbol`,
`validate_quantity`, `validate_columns`, `to_jsonable`, `safe_number`, `series_payload`, `strategy_id_constituents`,
`get_correlation_id`, `set_correlation_id`, `get_or_create_correlation_id`, `clear_correlation_id`, `traced`,
`CorrelationIdProcessor`, `TracingContext`, `init_otel_tracer`, `create_otel_span`, `OTEL_AVAILABLE`,
`IndicatorComputer`, `NullIndicatorComputer`, `SchemaExposure`, `DatasetSchema`, `ColumnSchema`.

## Dependencies

- Upstream: Python stdlib + pydantic v2.
- Downstream consumers: every layer (L1–L6, CLI, Web) imports `quantflow/common`.
- Security: `redact_secrets` scrubs logs; `validate_outbound_url` blocks SSRF; config priority CLI > ENV > YAML.

---

*Refreshed by codebase-refresh at 2026-08-02T14:30:00Z*
