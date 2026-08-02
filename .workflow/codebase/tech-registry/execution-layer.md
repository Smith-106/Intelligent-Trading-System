# TC-005 — ExecutionLayer

| Field | Value |
|-------|-------|
| **ID** | TC-005 |
| **Type** | L5-execution |
| **Features** | FT-005 (Execution) |
| **Last Updated** | 2026-08-02T14:30:00Z |

## Code Locations

- `quantflow/execution/gateway_base.py` — `GatewayBase` (ABC), `GatewayError`, `OpenOrder` (lightweight exchange-side order representation for reconciliation)
- `quantflow/execution/okx_gateway.py` — `OKXGateway` (CCXT async, spot/swap, reconnect)
- `quantflow/execution/paper_gateway.py` — `PaperGateway` (local simulation)
- `quantflow/execution/engine.py` — `ExecutionEngine` (kill-switch gate → route → track → metric → event → fill)
- `quantflow/execution/order_router.py` — `OrderRouter` (dispatch + `build_order`/`build_close_request`, extracted from engine)
- `quantflow/execution/order_manager.py` — `OrderManager` (lifecycle + timeout + RLock thread safety + atomic context manager + terminal-state guard)
- `quantflow/execution/position_manager.py` — `PositionManager` (per-route reconciliation)
- `quantflow/execution/kill_switch.py` — `KillSwitch` (emergency flatten, fail-closed)
- `quantflow/execution/__init__.py`

## Exported Symbols

`ExecutionEngine`, `GatewayBase`, `GatewayError`, `KillSwitch`, `OKXGateway`, `OpenOrder`, `OrderManager`,
`OrderRouter`, `PaperGateway`, `PositionManager`.

### Key Abstract Methods (GatewayBase)

- `connect(config)` / `disconnect()`
- `send_order(order) -> str`
- `cancel_order(id, symbol) -> bool`
- `query_positions() -> list[Position]`
- `query_open_orders(symbol) -> list[OpenOrder]` — orphan order detection for ReconciliationEngine (ISS-20260720-004)

## Dependencies

- Upstream: `quantflow/common` (models, exceptions), `quantflow/signal` (`PositionRequest`), `quantflow/strategy` (`TradingSession` drives submit).
- Downstream consumers: L3 `TradingSession`, CLI (`run` command), Web Station (`/api/session`, `/api/execution`).
- External: CCXT (OKX), Redis (optional state).
- Security: OKX creds from `OKX_API_KEY`/`OKX_SECRET`/`OKX_PASSPHRASE` env only; KillSwitch mandatory in live mode.

---

*Refreshed by codebase-refresh at 2026-08-02T14:30:00Z*
