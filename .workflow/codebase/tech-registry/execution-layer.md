# TC-005 — ExecutionLayer

| Field | Value |
|-------|-------|
| **ID** | TC-005 |
| **Type** | L5-execution |
| **Features** | FT-005 (Execution) |
| **Last Updated** | 2026-08-05T13:40:00Z |

## Code Locations

- `quantflow/execution/gateway_base.py`
- `quantflow/execution/okx_gateway.py`
- `quantflow/execution/paper_gateway.py`
- `quantflow/execution/engine.py`
- `quantflow/execution/order_router.py`
- `quantflow/execution/order_manager.py`
- `quantflow/execution/position_manager.py`
- `quantflow/execution/kill_switch.py`
- `quantflow/execution/__init__.py`
- `quantflow/execution/state_store.py`
- `quantflow/execution/exchange_health.py`

## Exported Symbols

- `CHECKPOINT_FILENAME` — Checkpoint file name
- `CALL_TIMEOUT` — HTTP call timeout (s) for OKX requests
- `CURRENT_SCHEMA_VERSION` — StateStore checkpoint schema version
- `DEFAULT_TIMEOUT` — Default gateway timeout (s)
- `EVENT_FILL` — Fill event type constant (common event bus)
- `EVENT_ORDER` — Order event type constant (common event bus)
- `ExchangeHealthMonitor` — Single-exchange circuit breaker (T-s1-04)
- `ExecutionEngine`
- `GatewayBase`
- `GatewayError`
- `KillSwitch`
- `MAX_RECONNECT_ATTEMPTS` — Max WebSocket reconnect attempts
- `MAX_TRACKED_ORDERS` — OrderManager max tracked order count
- `OKXGateway`
- `OpenOrder`
- `OrderManager`
- `OrderRouter`
- `PaperGateway`
- `PositionManager`
- `RECONNECT_INTERVAL` — WebSocket reconnect interval (s)
- `RECOVERY_SUCCESS_STREAK` — Consecutive successes needed to close breaker
- `SessionSnapshot` — Serializable session state dataclass
- `StateStore` — Checkpoint state store for crash-recovery

## Dependencies

- Upstream: `quantflow/common` (models, exceptions, config).
- Downstream consumers: see feature maps for consumer wiring.

---

*Refreshed by codebase-refresh at 2026-08-05T05:39:39Z*
