# TC-005 — ExecutionLayer

| Field | Value |
|-------|-------|
| **ID** | TC-005 |
| **Type** | L5-execution |
| **Features** | FT-005 (Execution) |

## Code Locations

- `quantflow/execution/gateway_base.py:15` — `GatewayBase(ABC)` (`connect`, `send_order`, `cancel_order`, `query_positions`; optional `disconnect`, `cancel_all_orders`, `subscribe`)
- `quantflow/execution/okx_gateway.py:50` — `OKXGateway` (CCXT async, sandbox/live, reconnect; ISS-005 `market_type` spot/swap ctor param — validates spot|swap, connect honors `options.defaultType`, `query_positions` dual-branch `_query_swap_positions`/`_query_spot_positions`; ISS-011 `monitoring_sink` ctor param, connect/disconnect/ensure_connected/send_order/query_positions emit `record_gateway_*` via `_record_disconnect` helper)
- `quantflow/execution/paper_gateway.py:8` — `PaperGateway` (local simulation, immediate fills)
- `quantflow/execution/engine.py:30` — `ExecutionEngine` (orchestrates submit: kill-switch gate → router.route → track → metric → event → `_handle_fill`; owns gateway lifecycle `start`/`stop`/`connect`/`disconnect`; routing/order-construction delegated to `OrderRouter` since ISS-003)
- `quantflow/execution/order_router.py:34` — `OrderRouter` (gateway dispatch `route` + Order construction `build_order` + close-position `build_close_request` reduceOnly + `is_closeable` POSITION_EPSILON guard; arch-017 lazy `set_gateway` binding, constructed unbound, rebound in `ExecutionEngine.start`; ISS-003 extracted from ExecutionEngine god-object)
- `quantflow/execution/order_manager.py:30` — `OrderManager` (pending tracking, timeout checks; ISS-011 `monitoring_sink` ctor param, `check_timeouts` emits `record_order_timed_out`)
- `quantflow/execution/position_manager.py:7` — `PositionManager` (thin delegate over L4 `PortfolioManager` — Wave 2 退化: `__init__(portfolio=None)` 默认自建 + `bind_portfolio()` 重绑; 全 9 方法委托 L4)
- `quantflow/execution/kill_switch.py:8` — `KillSwitch` (emergency flatten, wraps `GatewayBase`; best-effort — catches per-step exceptions into `results["errors"]`)

## Exported Symbols

`ExecutionEngine`, `GatewayBase`, `GatewayError`, `KillSwitch`, `OKXGateway`, `OrderManager`, `OrderRouter`, `PaperGateway`, `PositionManager`

## Dependencies

- **Imports**: `common`, `common.monitoring_sink` (Protocol injection, ISS-019/044 + ISS-011). `metrics`/`alerts` calls route through the injected `MonitoringSink` — **no direct `quantflow.monitoring.*` imports** in execution layer (ISS-044 closed the lazy-import audit-evasion). ISS-011 extended sink consumers beyond `ExecutionEngine`+`KillSwitch` to also `OKXGateway` (gateway connected/disconnect/reconnect) + `OrderManager` (order timed_out). `OrderRouter` holds no sink — pure dispatch/construction helper.
- **Imported by**: `strategy/engine` (orchestrator), `web/` (session_manager).

## Notes

- **Three execution modes**: paper (`PaperGateway`) / sandbox (OKX testnet) / live (OKX). Gateway selected in `ExecutionEngine.start` based on `mode`.
- **OKX credentials from env vars only** — `cli/main.py:61-81` `_load_gateway_config_from_env` requires `OKX_API_KEY`/`OKX_SECRET`/`OKX_PASSPHRASE` for non-paper; `web/session_manager.py:33-50` same.
- **ISS-021 paper/live parity (fixed)**: `PaperGateway` now honors `reduceOnly` (paper_gateway.py:85) — a reduceOnly SELL only flattens a long (never flips into a new short), matching OKX live exchange semantics. Previously paper ignored reduceOnly, causing paper/live divergence.
- **ISS-044 L6 解耦 (fixed)**: `ExecutionEngine` (engine.py:45,57) + `KillSwitch` accept `monitoring_sink: MonitoringSink | None = None` (default `NullMonitoringSink`). All 4 metric call sites (159/203 `record_order_total`, 237 `record_order_filled`, 272 `record_order_latency`) route through `self._sink`. `_record_order_latency` converted static→instance method.
- **ISS-20260720-004 Wave 2 (L5 薄路由退化, 2026-07-25)**: `PositionManager` 退化为薄路由委托 L4 `PortfolioManager`(全 9 方法委托: `update_position`→L4 含 fee, `set_position`→L4, `close_position`→`update_position(-qty)`, `get_position`/`get_all_positions`/`has_position`/`position_count`/`total_unrealized_pnl`/`total_market_value`→委托)。`PaperGateway` 移除第三套 `_cash` 账本(fee 仅盖印 `order.fee`,L4 单扣;保留 `_positions` 作 gateway 本地交易所视图,与 `OKXGateway` 对称)。消除 L5 委托 L4 后 `engine.submit` + `_process_signal` 双计同一 fill 的风险。commit `062a7b5`。
- **ISS-20260720-004 Wave 4 (partial-fill cumulative 契约, 2026-07-25)**: `Order.applied_filled_qty` 跟踪已应用 L4 的累计量,`ExecutionEngine.submit` 派生 `delta_filled = filled_quantity - applied_filled_qty`,仅当 `delta_filled > POSITION_EPSILON` 时调 L4 `update_position`(防重复回调误调),FILLED 才 emit EVENT_FILL。`OKXGateway.send_order` 从 ccxt result 提取 cumulative filled/average/fee.cost 盖印。commit `b0177e0`。
- **ISS-20260723-003 OrderRouter 抽取 (2026-07-27, commit c51d571)**: `order_router.py:34` `OrderRouter` 拥有 gateway dispatch (`route`) + Order 构造 (`build_order`) + 平仓请求 (`build_close_request` reduceOnly) + `is_closeable` 守卫。arch-017 lazy binding: 构造时 `gateway=None`,`ExecutionEngine.start` 后 `set_gateway` 重绑(与 `set_portfolio` 同构)。`ExecutionEngine.submit` 降级为编排(kill_switch → router.route → track → metric → event → `_handle_fill`);`close_position` 用 `router.is_closeable`/`build_close_request`。退役 ExecutionEngine god-object 形态(原 7 职责)。
- **ISS-20260723-005 OKXGateway market_type spot/swap (2026-07-27, commit 0c89957)**: `OKXGateway.__init__(market_type='spot')` 校验 spot|swap; connect 用 `options.defaultType`; `query_positions` 双分支 — `_query_swap_positions` 读 contracts/entryPrice/markPrice/unrealizedPnl;`_query_spot_positions` 从 `fetch_balance` 派生非 quote 资产(排除 USDT/USDC/USD/DAI),entry_price=0/unrealized_pnl=0(spot 无杠杆)。`ExecutionConfig.market_type`(`common/config.py:96`,默认 `spot`)+ `config/default.yaml` execution.market_type 驱动分支。
- **ISS-20260723-011 L6 Protocol 扩展 OBS-M 集群 (2026-07-27, commit 08d7032)**: `MonitoringSink` Protocol +4 方法(record_gateway_connected/record_gateway_disconnect/record_gateway_reconnect/record_order_timed_out),`NullMonitoringSink` +4 no-op,`DefaultMonitoringSink` +4 实现,`monitoring/metrics.py` +4 prometheus(GATEWAY_CONNECTED gauge + GATEWAY_DISCONNECTS/GATEWAY_RECONNECTS/ORDERS_TIMED_OUT counter)。`OKXGateway`(connect/disconnect/ensure_connected/send_order/query_positions 经 `_record_disconnect` helper)+ `OrderManager`(`check_timeouts`)为两新 L5 消费者。`risk_engine` rejection log 加 details+symbol。
- **Kill switch live enforcement (fixed)**: `web/session_manager.py:167` rejects `mode in ("live","sandbox")` + `kill_switch_enabled=False` — closes the CLAUDE.md "实盘必须启用 Kill Switch" gap (was config-flag-only with no assertion).
- **⚠️ Event constant duplication**: `execution/engine.py:27-28` locally redefines `EVENT_ORDER`/`EVENT_FILL` instead of importing from `common/models.py:50-51` — dedup candidate (single source of truth).
- **KillSwitch best-effort flatten**: `activate()` catches broad `except Exception` into `results["errors"]` and logs without re-raising — deliberate resilience for emergency flatten.

*Auto-generated by codebase-refresh at 2026-07-25T00:00:00Z, drift-realign updated 2026-07-28 (ISS-003/005/011 batch)*
