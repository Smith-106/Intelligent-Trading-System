---
title: "Coding Conventions"
category: coding
---
# Coding Conventions

Auto-generated from project analysis. Update manually as patterns evolve.

## Formatting
- Indentation: 4 spaces (Python standard)
- Line length: 100 (ruff)
- Trailing commas: yes (multi-line structures)
- Semicolons: no (Python)

## Naming
- Variables/functions: snake_case
- Classes/types: PascalCase
- Constants: UPPER_SNAKE_CASE
- Files: snake_case.py
- Private methods: _leading_underscore
- Pydantic models: PascalCase
- Enum members: UPPER_SNAKE_CASE

## Imports
- Style: named imports (from ... import ...)
- Path aliases: none (quantflow.xxx absolute imports)
- Order: stdlib → third-party → first-party (ruff isort, known-first-party = ["quantflow"])
- Always use `from __future__ import annotations`

## Patterns
- Type annotations on all function signatures (return types + params)
- Use `|` union syntax (Python 3.10+ style)
- Google/NumPy docstrings on classes and public methods
- Pydantic v2 for config/data validation
- structlog for structured logging
- async/await throughout (CCXT async, WebSocket, gateway)
- Abstract base classes for interfaces (StrategyBase, GatewayBase, FactorBase)

## Entries

<spec-entry category="coding" keywords="策略双模式,generate_signals,on_bar,向量化,事件驱动" date="2026-06-13" title="策略双模式: generate_signals 向量化 + on_bar 事件驱动" description="策略模板标准双 API 模式">
### 策略双模式: generate_signals 向量化 + on_bar 事件驱动

所有策略模板遵循双模式：
1. `generate_signals(df)` — 向量化研究/回测 API，输入完整 DataFrame，输出 (entries, exits) boolean Series
2. `on_bar(ctx, bar)` — 事件驱动 live/paper API，接收单根 bar，通过 emit_signal 生成信号

两种模式必须保证信号 parity，通过确定性 fixture 测试验证。

**来源**: PLAN-001 DD-004 设计决策
**模式参考**: trend_following.py 双模式实现
</spec-entry>

<spec-entry category="coding" keywords="search,codegraph,代码搜索" date="2026-06-01">

### mcp-semantic-search

代码搜索优先使用 CodeGraph MCP（`mcp__codegraph__codegraph_context`），精确符号查找用 `codegraph_search`/`codegraph_callers`，简单文本匹配用 Grep

</spec-entry>

<spec-entry category="coding" keywords="validate-symbol,write-path,path-traversal,choke-point,symmetric-validation" date="2026-07-05" title="Validate symbol at EVERY symbol→path/glob site — read, write, AND in-place transform" description="Write/transform paths must call validate_symbol symmetric with reads; a direct Path construction bypasses the DataStore choke point">
### Validate symbol at EVERY symbol→path/glob site — read, write, AND in-place transform

Every code path that turns a user/operator-supplied symbol into a filesystem path OR a DuckDB glob literal must pass through `quantflow.common.validators.validate_symbol()`. This includes:

- **Read paths** — `DataStore.query`, `get_date_range`, `FeatureStore.load_features` (validate before interpolating into `read_parquet('...{symbol}...')`).
- **Write paths** — `DataStore.save`, `FeatureStore.save_features` (validate before `Path(parquet_dir)/symbol_name`).
- **In-place transform paths** — any service-layer handler that constructs a `Path` directly (e.g. `web/service.py:tag_data_source`). Do NOT rely on "the downstream DataStore call validates" — a direct `Path` construction runs FIRST and bypasses the choke point.

Anti-pattern: `symbol.replace('/', '_')` without `validate_symbol` — leaves a path-traversal (CWE-22) + SQL-injection-via-glob (CWE-89) surface. The read path validated but the write/transform path didn't (asymmetric validation).

The choke point is `validate_symbol` (public, not underscored — see arch spec on security primitives). `SYMBOL_PATTERN` rejects quotes, backslashes, dots, glob metachars (`*` `[`), shell metachars, spaces, and >20-char strings.

Durable guard: `tests/unit/test_trend_and_store.py::test_validate_symbol_rejects_security_relevant_chars` (14 parametrized cases).

Source: odyssey-review security-fixes session (REV-008 + sibling G4 in service.py).
</spec-entry>

<spec-entry category="coding" keywords="auto-commit,ruff,lint-gate,pre-commit,workflow-discipline" date="2026-07-05" title="Run ruff check --fix && ruff format before every auto-commit (lint-before-commit gate)" description="Workflow phase auto-commits must lint/format first or CI's ruff gate goes red; defense-in-depth via .pre-commit-config.yaml">
### Run ruff check --fix && ruff format before every auto-commit (lint-before-commit gate)

Any workflow action that does `git add` + `git commit` on generated/edited Python MUST run the project-mandated lint/format pipeline immediately before `git add`, and abort the commit on lint failure:

```bash
ruff check --fix . && ruff format .
if ! ruff check . ; then echo "lint failed; aborting commit"; exit 1; fi
git add <files> && git commit -m "..."
```

Without this gate, every auto-commit can drift past the CI quality bar; errors compound across a multi-phase session (one deepfix session accumulated 200+ ruff errors across 30 test files before anyone noticed). Subagent-generated test files are the most common vector (large, written in bulk, never individually formatted).

Defense-in-depth: a repo-level `.pre-commit-config.yaml` (ruff `--fix` + ruff-format hooks, pinned to the project ruff version) enforces this at the git layer even when the workflow reminder is missed. Both layers are intentional.

Detection: CI `ruff format --check` + `ruff check` go red on `main` shortly after the offending commit; failing files cluster in one command's session window (`git log --oneline -- <file>`). When CI ruff fails on files all from one session, suspect this pattern, not a config change.

Source: odyssey-debug ci-ruff-breakage session (P1). Implemented as a maestro overlay on the odyssey-*.md wrappers + `.pre-commit-config.yaml`.
</spec-entry>

<spec-entry category="coding" keywords="look-ahead,vectorized,signal-generator,entries-mask,forward-fill" date="2026-07-05" title="No look-ahead in vectorized signal generators — never aggregate over entries[bool_mask]" description="series[entries].mean() uses future bar data at the entry bar; capture value at entry + forward-fill for position lifetime">
### No look-ahead in vectorized signal generators — never aggregate over entries[bool_mask]

In a vectorized `generate_signals(df)`, any `series[entries].mean()` / aggregation over a boolean entry mask uses **future** bar data at the entry bar — a look-ahead bug. The masked values are computed from the full series, so the entry-bar value already reflects information only known later.

Fix pattern: capture the value at the entry bar and forward-fill it for the position lifetime. Canonical helper: `profit_target_exit_series` in `strategy/templates/_runtime.py` — computes a per-bar `effective_pct_series` (e.g. RSI-adaptive tight/wide multiplier) forward-filled from the entry bar, so each bar during the position sees only the entry-bar decision.

Scan: all `generate_signals` implementations + indicator factories that consume `entries`/`exits` masks. The v0.1.3 perf run introduced 3 CRITICAL look-ahead regressions (trend_following RSI profit-target, momentum_rotation cross-sectional rank, FLAT-as-SELL). Perf optimization without a correctness gate breeds these — any "perf optimize X" change MUST be followed by a look-ahead audit of the vectorized signal path before merge.

Source: odyssey-review deepfix session (Pattern 1, CRITICAL fixes 1-3).
</spec-entry>


<spec-entry category="coding" keywords="vectorbt,参数扫描,向量化,multi-asset,broadcasting" date="2026-07-18" sid="S-20260718-sffn" status="contested" contested_by="ISS-20260722-001" title="研究层大规模参数扫描用 vectorbt run_combs/Portfolio.from_signals 多资产 broadcasting" description="用 run_combs/Portfolio.from_signals 多资产 broadcasting 替代 Python 循环做大规模参数扫描" source="harvest:deep-research-20260718">

### 研究层大规模参数扫描用 vectorbt run_combs/Portfolio.from_signals 多资产 broadcasting

[CONTESTED — 见条目末冲突说明]

研究层应充分利用 vectorbt 的向量化参数扫描:放弃逐 bar 循环,把数千策略配置打包进 NumPy 数组做向量化评估(Numba+Rust 加速热路径),支持多资产 broadcasting 的大规模参数扫描(如 vbt.MA.run_combs(price, window=np.arange(2,101), r=2) 跨 BTC/ETH/XRP,将小时级网格搜索压缩到秒级)。需核实 strategy/research/ 当前是否仍用 Python 循环,若是则迁移到 run_combs/Portfolio.from_signals。注: vectorbt 活跃维护(2026-07 仍有提交);Numba JIT 路径在小数据集上可能产生 cryptic error 与延迟,热路径需基准测试。来源: deep-research-20260718 F6-参考项目 (3-0 verified), polakowo/vectorbt。

**[CONFLICT — 待审计裁决]**: 本条目建议迁移到 vectorbt，但 `quantflow/strategy/research/backtest.py:1-4` 注释明确已**故意移除** vectorbt（Python 3.14/numba 不兼容），全仓零 vectorbt 引用。架构决策与 spec 直接矛盾。ISS-20260722-001 待审计三选一：(a) 撤销迁移方向，重定向 numpy 向量化+并行化（与现状一致，本条目应 deprecated）；(b) 重新评估 vectorbt 2026 兼容性；(c) 保留但维持 contested。grill 倾向 (a)。在裁决前，本条目以 `status="contested"` 标注，search 权重 ×0.5，仍注入但不作为实施依据。裁决入口：`/manage-knowledge-audit --scope spec`。
</spec-entry>

<spec-entry category="coding" keywords="compound,strategy_id,allocation,consolidated-signal,exact-lookup,silent-drop" date="2026-07-20" sid="S-20260720-98vs" title="Compound strategy_id 精确查找静默失效" description="compound strategy_id 精确查找静默失效范式——consolidated signal 的 joined key 永远 miss，返回 0.0 致信号丢弃/预算 bypass" source="main@428002d">

### Compound strategy_id 精确查找静默失效

consolidated signal 携带逗号拼接的 compound strategy_id（如 "momentum_rotation,trend_following"）。任何以 strategy_id 为 key 的 dict.get(exact_key, default) / exact-match 查找（allocation、win_rate、hit_rate、risk_budget、order 查询）对 compound key 永远 miss，静默返回 default（通常 0.0）——信号被 size*0 丢弃在 engine.py:313，或 risk budget 被静默 bypass。修复模板：(1) 用 strategy_id_constituents(id) 展开为 constituents list；(2) 对每个 constituent 查找并求和/聚合（allocation 求和、win_rate 加权平均、risk budget 逐 constituent 强制）；(3) 非 compound 时回退原始 raw id 查找。所有消费 compound-key signal 的 dict 必须用此展开。已知修复点：portfolio.get_strategy_allocation (CORR-H1, ISS-20260720 odyssey)、risk_engine._check_strategy_budget (ISS-20260613-006 family)、position_sizer.size win-rate blending。守卫：新写任何 dict[str,X] keyed by strategy_id 的消费者前，grep 确认是否处理 compound。

</spec-entry>

<spec-entry category="coding" keywords="fail-silent,fail-open,error-path,sentinel,no-go,fail-closed" date="2026-07-24" sid="S-20260724-elsu" title="fail-silent fallback 不可复用合法结果值" description="except 路径不可返回与合法结果不可区分的值；用 NaN+排除 或 fail-closed sentinel" source="main@bb3c6cd">

### fail-silent fallback 不可复用合法结果值

except Exception 路径不可返回与合法结果不可区分的值（0.0/True/neutral/{0.33,0.33,0.34}/365/-10.0）。这种 fail-silent/fail-open 碰撞会：(1) 偏置聚合指标（DSR _expected_max_sharpe 返 0.0 使多重检验惩罚失效；PBO/WFO per-path 返 0.0 低估过拟合；backtest _periods_per_year 返 365 使 intraday 年化低估 ~24x）；(2) 静默禁用安全门（ml_ensemble._apply_meta_filter 返 pd.Series(True) approve-all 使 meta-model 失败时 meta-labeling 风险过滤失效；sentiment.analyze_text 返 neutral 使失败注入中性偏差）。修复模式：错误路径返回值 NO 合法结果会产出——NaN sentinel + 聚合时排除，或 fail-closed sentinel（+inf/False）强制 NO-GO。绝不复用结果值作错误路径返回。

</spec-entry>

<spec-entry category="coding" keywords="monitoring,layering,protocol,sink,l6,injection" date="2026-07-24" sid="S-20260724-3i37" title="L6 可观测性跨层契约走 common/ Protocol 注入，lower layer 不 import monitoring/" description="L6 可观测性跨层契约：common/ Protocol + Null 默认 + 高层注入，lower layer 不 import monitoring/" source="main@98b217e">

### L6 可观测性跨层契约走 common/ Protocol 注入，lower layer 不 import monitoring/

L3 strategy/engine、L4 signal/risk_engine、L5 execution/engine+kill_switch 需要 push 指标/发告警时，禁止直接 import quantflow.monitoring.* 具体类（top-level 或 in-function lazy，后者额外违反 arch-013 audit-evasion）。固定模式：在 common/monitoring_sink.py 定义 runtime_checkable Protocol（MonitoringSink：start/record_signal/record_bar_latency/record_signal_latency/record_portfolio/send_alert）+ NullMonitoringSink（零开销默认，backtest/tests 用）；monitoring/sink.py 实现 DefaultMonitoringSink（owns AlertManager 生命周期 + idempotent per-port metrics-server start）；调用方（cli/main、web/session_manager 高层）注入 create_default_sink()，lower layer 构造函数接受 monitoring_sink: MonitoringSink | None = None 默认 Null。EventBus 保留给 control flow（BAR/SIGNAL/RISK/ORDER/FILL），observability side-effect 走 sink Protocol——避免为 telemetry 膨胀 event 契约。ISS-019 落地 L3 strategy/engine（commit 1bf8e2b）；ISS-20260724-044 落地 3 sibling 站点——risk_engine:90 in-function RISK_EVENTS lazy-import（audit-evasion）、kill_switch:11 KILL_SWITCH_ACTIVATIONS/STEP_FAILURES、execution/engine:25 ORDER_LATENCY/ORDERS_FILLED/ORDERS_TOTAL 全部改走 self._sink.record_*（commit b2a4cf8，Protocol 扩展 6 个 record 方法）。L1-L5 现零 monitoring/ 直接 import。

</spec-entry>

<spec-entry category="coding" keywords="翻仓,realized,closing-qty,snapshot,portfolio" date="2026-07-25" sid="S-20260725-3zl0" title="翻仓 realized 归因实现模式(PortfolioManager.update_position): 在 cash mutation 后追加: if existing.quantity * quantity_delta &lt; 0: closing_qty = min(abs(quantity_delta), abs(existing.quantity)); sign = 1.0 if existing.quantity &gt; 0 else -1.0; self._realized_pnl += (price - existing.entry_price) * closing_qty * sign。仅当方向反转(乘积&lt;0)触发, 部分平仓取 min(delta, existing) 防超平。snapshot 经 Portfolio dataclass realized_pnl 字段暴露(默认 0.0 保后向兼容)。测试: 翻仓双向(long→short / short→long)+ 部分平仓 realized 累计 + snapshot 暴露。" description="翻仓 realized 归因代码模式: closing_qty*sign 累计 + snapshot 暴露" source="main@06a8d93">

### 翻仓 realized 归因实现模式(PortfolioManager.update_position): 在 cash mutation 后追加: if existing.quantity * quantity_delta < 0: closing_qty = min(abs(quantity_delta), abs(existing.quantity)); sign = 1.0 if existing.quantity > 0 else -1.0; self._realized_pnl += (price - existing.entry_price) * closing_qty * sign。仅当方向反转(乘积<0)触发, 部分平仓取 min(delta, existing) 防超平。snapshot 经 Portfolio dataclass realized_pnl 字段暴露(默认 0.0 保后向兼容)。测试: 翻仓双向(long→short / short→long)+ 部分平仓 realized 累计 + snapshot 暴露。



</spec-entry>

<spec-entry category="coding" keywords="cumulative-fill,delta,position-epsilon,partial,applied-filled-qty" date="2026-07-25" sid="S-20260725-j4x6" title="cumulative-fill delta 守卫实现模式(ExecutionEngine.submit FILLED/PARTIAL 分支): delta_filled = order.filled_quantity - order.applied_filled_qty; if delta_filled &gt; POSITION_EPSILON: qty_signed = delta_filled if order.side==BUY else -delta_filled; position_mgr.update_position(symbol, qty_signed, filled_price, fee=order.fee, strategy_id=...); order.applied_filled_qty = order.filled_quantity。FILLED 才 emit EVENT_FILL + record_order_filled; PARTIAL 保持 non-terminal(OrderManager get_open_orders 含 PARTIAL, _pending 不 pop)。POSITION_EPSILON 来自 common.validators, 防 delta=0 重复回调误调 L4。Order.applied_filled_qty 默认 0.0 保后向兼容。" description="cumulative-fill delta 守卫代码模式 + PARTIAL 状态保留" source="main@06a8d93">

### cumulative-fill delta 守卫实现模式(ExecutionEngine.submit FILLED/PARTIAL 分支): delta_filled = order.filled_quantity - order.applied_filled_qty; if delta_filled > POSITION_EPSILON: qty_signed = delta_filled if order.side==BUY else -delta_filled; position_mgr.update_position(symbol, qty_signed, filled_price, fee=order.fee, strategy_id=...); order.applied_filled_qty = order.filled_quantity。FILLED 才 emit EVENT_FILL + record_order_filled; PARTIAL 保持 non-terminal(OrderManager get_open_orders 含 PARTIAL, _pending 不 pop)。POSITION_EPSILON 来自 common.validators, 防 delta=0 重复回调误调 L4。Order.applied_filled_qty 默认 0.0 保后向兼容。



</spec-entry>

<spec-entry category="coding" keywords="薄路由,委托,positionmanager,bind-portfolio,本地视图" date="2026-07-25" sid="S-20260725-jabg" title="L5 PositionManager 薄路由委托模式: __init__(portfolio=None) 默认自建 PortfolioManager(standalone/test), bind_portfolio(portfolio) 重绑共享 L4。全 9 方法委托: update_market_price→update_market_prices({sym:price}); update_position→委托 L4(含 fee); set_position→委托; get_position/get_all_positions/has_position/position_count/total_unrealized_pnl/total_market_value→委托; close_position→update_position(-pos.quantity, current_price)(真平仓经 L4)。ExecutionEngine.sync_positions 改 self._position_mgr.set_position(pos.symbol, pos)(替代私有属性写, exchange 是 live sync 真值源覆盖本地 book)。PaperGateway 移除 _cash 第三套账本, fee 仅盖印 order.fee(L4 单扣), 保留 _positions 本地视图(query_positions/reduceOnly caps)。" description="L5 薄路由委托模式 + PaperGateway 本地视图" source="main@06a8d93">

### L5 PositionManager 薄路由委托模式: __init__(portfolio=None) 默认自建 PortfolioManager(standalone/test), bind_portfolio(portfolio) 重绑共享 L4。全 9 方法委托: update_market_price→update_market_prices({sym:price}); update_position→委托 L4(含 fee); set_position→委托; get_position/get_all_positions/has_position/position_count/total_unrealized_pnl/total_market_value→委托; close_position→update_position(-pos.quantity, current_price)(真平仓经 L4)。ExecutionEngine.sync_positions 改 self._position_mgr.set_position(pos.symbol, pos)(替代私有属性写, exchange 是 live sync 真值源覆盖本地 book)。PaperGateway 移除 _cash 第三套账本, fee 仅盖印 order.fee(L4 单扣), 保留 _positions 本地视图(query_positions/reduceOnly caps)。



</spec-entry>