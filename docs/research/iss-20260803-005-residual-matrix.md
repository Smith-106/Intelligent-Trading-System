# ISS-20260803-005 Residual Matrix (Wave A2)

**Date**: 2026-08-08T17:10:59+08:00
**Issue**: paper/live parity gaps — partial-fill / regime dual-path / PaperGateway params

| Area | Claim in issue | Code evidence | Tests | Disposition |
|------|----------------|---------------|-------|-------------|
| Partial-fill cumulative book | partial-fill via ws 回调未全链路 | `ExecutionEngine._handle_fill` delta via `applied_filled_qty`; `PortfolioManager.partial_confirm` cumulative notional (M4-5.14); `OrderManager` partial tracking; OKX cumulative extract | `test_execution.py::test_partial_fill_increments_l4_cumulative`; `test_execution_engine.py` cumulative/partial+cancel; `test_m4_paper_partial_fill.py` (6); `test_m4_pending_lifecycle` | **done** |
| Paper partial simulation | Paper 无法演练 partial | `PaperGateway.partial_fill_ratio` opt-in (M4-5.15) | `test_m4_paper_partial_fill.py` | **done** |
| reduceOnly / params 透传 | PaperGateway 忽略 order.params/reduceOnly (ISS-021) | `paper_gateway.py` honors `order.params["reduceOnly"]` (reject/cap); `okx_gateway` forwards params; `OrderRouter.build_close_request` sets reduceOnly; kill-switch uses `_REDUCE_ONLY_PARAMS` | `test_execution.py` reduce_only_* (3); `test_m4_paper_partial_fill::test_reduce_only_cap_applied_before_partial_ratio`; `test_order_router` close reduceonly | **done** |
| Regime gate 双路 | on_bar regime vs generate_signals 无 regime | Documented two-layer design: regime=macro ADX gate on paper/live path; `generate_signals` research API intentionally without regime (`strategy/base.py`, `trend_following.py` note, `engine.py` comments). Parity: paper entries ⊆ vectorized when regime gates | `test_engine_extra` regime gates; `test_strategies` regime_gates_some_vectorized_entries; `test_backtest_paper_parity` paper subset of backtest | **by-design** (not a bug; live-faithful research uses on_bar/paper_replay) |
| kill_switch comment drift | comment still claims Paper ignores params | Stale comment only — implementation already honors reduceOnly | N/A | **doc-fix** in A2 |

## Residual (optional, out of mother-issue scope)

| ID | Scope | Why not blocking 005 close |
|----|-------|----------------------------|
| none opened | Full exchange WS 8-state formal model coverage beyond cumulative partial path | Core partial/reduceOnly/regime items from harvest text are satisfied; broader formal 8-state matrix can be future hardening if needed |

## Pytest (2026-08-08)

```
pytest tests/unit/test_execution.py tests/unit/test_m4_paper_partial_fill.py   tests/unit/test_execution_engine.py tests/unit/test_engine_extra.py   -k "partial or reduce or regime" → 16 passed
```

## Mother-issue disposition

**ISS-20260803-005 → resolved** (done + by-design; no residual child issue required).
