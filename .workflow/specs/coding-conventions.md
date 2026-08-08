---
title: "Coding Conventions"
category: coding
related:
  - DOC-knowledge-hub
type: spec
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
- structlog for structured logging — `setup_logging()` bridges stdlib `logging` via `structlog.stdlib.ProcessorFormatter`; modules use `logging.getLogger(__name__)` and render through the structlog pipeline (see debug-notes 日志规范)
- async/await throughout (CCXT async, WebSocket, gateway)
- Abstract base classes for interfaces (StrategyBase, GatewayBase, FactorBase)

## Entries

<spec-entry category="coding" keywords="策略双模式,generate_signals,on_bar,向量化,事件驱动" date="2026-06-13" title="策略双模式: generate_signals 向量化 + on_bar 事件驱动" description="策略模板标准双 API 模式" sid="S-legacy-ba5131ad">
### 策略双模式: generate_signals 向量化 + on_bar 事件驱动

所有策略模板遵循双模式：
1. `generate_signals(df)` — 向量化研究/回测 API，输入完整 DataFrame，输出 (entries, exits) boolean Series
2. `on_bar(ctx, bar)` — 事件驱动 live/paper API，接收单根 bar，通过 emit_signal 生成信号

两种模式必须保证信号 parity，通过确定性 fixture 测试验证。

**来源**: PLAN-001 DD-004 设计决策
**模式参考**: trend_following.py 双模式实现
</spec-entry>

<spec-entry category="coding" keywords="search,codegraph,代码搜索" date="2026-06-01" sid="S-legacy-b23e2d8a">

### mcp-semantic-search

代码搜索优先使用 CodeGraph MCP（`mcp__codegraph__codegraph_context`），精确符号查找用 `codegraph_search`/`codegraph_callers`，简单文本匹配用 Grep

</spec-entry>

<spec-entry category="coding" keywords="validate-symbol,write-path,path-traversal,choke-point,symmetric-validation" date="2026-07-05" title="Validate symbol at EVERY symbol→path/glob site — read, write, AND in-place transform" description="Write/transform paths must call validate_symbol symmetric with reads; a direct Path construction bypasses the DataStore choke point" sid="S-legacy-37e8dce4">
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

<spec-entry category="coding" keywords="auto-commit,ruff,lint-gate,pre-commit,workflow-discipline" date="2026-07-05" title="Run ruff check --fix && ruff format before every auto-commit (lint-before-commit gate)" description="Workflow phase auto-commits must lint/format first or CI's ruff gate goes red; defense-in-depth via .pre-commit-config.yaml" sid="S-legacy-df8312a6">
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

<spec-entry category="coding" keywords="look-ahead,vectorized,signal-generator,entries-mask,forward-fill" date="2026-07-05" title="No look-ahead in vectorized signal generators — never aggregate over entries[bool_mask]" description="series[entries].mean() uses future bar data at the entry bar; capture value at entry + forward-fill for position lifetime" sid="S-legacy-d41a7358">
### No look-ahead in vectorized signal generators — never aggregate over entries[bool_mask]

In a vectorized `generate_signals(df)`, any `series[entries].mean()` / aggregation over a boolean entry mask uses **future** bar data at the entry bar — a look-ahead bug. The masked values are computed from the full series, so the entry-bar value already reflects information only known later.

Fix pattern: capture the value at the entry bar and forward-fill it for the position lifetime. Canonical helper: `profit_target_exit_series` in `strategy/templates/_runtime.py` — computes a per-bar `effective_pct_series` (e.g. RSI-adaptive tight/wide multiplier) forward-filled from the entry bar, so each bar during the position sees only the entry-bar decision.

Scan: all `generate_signals` implementations + indicator factories that consume `entries`/`exits` masks. The v0.1.3 perf run introduced 3 CRITICAL look-ahead regressions (trend_following RSI profit-target, momentum_rotation cross-sectional rank, FLAT-as-SELL). Perf optimization without a correctness gate breeds these — any "perf optimize X" change MUST be followed by a look-ahead audit of the vectorized signal path before merge.

Source: odyssey-review deepfix session (Pattern 1, CRITICAL fixes 1-3).
</spec-entry>


<spec-entry category="coding" keywords="vectorbt,参数扫描,向量化,multi-asset,broadcasting" date="2026-07-18" sid="S-20260718-sffn" status="deprecated" superseded_by="ISS-20260722-001" title="研究层大规模参数扫描用 vectorbt run_combs/Portfolio.from_signals 多资产 broadcasting" description="DEPRECATED — vectorbt 因 Python 3.14/numba 不兼容已移除，改用 numpy 向量化+并行化" source="harvest:deep-research-20260718">

### 研究层大规模参数扫描用 vectorbt run_combs/Portfolio.from_signals 多资产 broadcasting

**[DEPRECATED — ISS-20260722-001 裁决结果]**

本条目建议迁移到 vectorbt，但架构决策已明确否决：`quantflow/strategy/research/backtest.py:1-4` 注释记录 vectorbt 因 **Python 3.14/numba 不兼容** 被故意移除，全仓零 vectorbt 引用。ISS-20260722-001 审计结论 (a)：撤销迁移方向，本条目 `status` 由 `contested` 改为 `deprecated`。

**当前架构**：研究层参数扫描采用 numpy 向量化 + 并行化（`BacktestEngine` 纯 pandas/numpy 实现），在 Python 3.14+ 环境下稳定运行。本条目的 vectorbt 迁移建议已被架构决策取代，不再作为实施依据。

原始条目保留如下以供历史追溯：研究层应充分利用 vectorbt 的向量化参数扫描...（已废弃）。
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

L3 strategy/engine、L4 signal/risk_engine、L5 execution/engine+kill_switch 需要 push 指标/发告警时，禁止直接 import quantflow.monitoring.* 具体类（top-level 或 in-function lazy，后者额外违反 arch-013 audit-evasion）。固定模式：在 common/monitoring_sink.py 定义 runtime_checkable Protocol（MonitoringSink）+ NullMonitoringSink（零开销默认，backtest/tests 用）；monitoring/sink.py 实现 DefaultMonitoringSink（owns AlertManager 生命周期 + idempotent per-port metrics-server start）；调用方（cli/main、web/session_manager 高层）注入 create_default_sink()，lower layer 构造函数接受 monitoring_sink: MonitoringSink | None = None 默认 Null。EventBus 保留给 control flow（BAR/SIGNAL/RISK/ORDER/FILL），observability side-effect 走 sink Protocol——避免为 telemetry 膨胀 event 契约。ISS-019 落地 L3 strategy/engine（commit 1bf8e2b）；ISS-20260724-044 落地 3 sibling 站点——risk_engine:90 in-function RISK_EVENTS lazy-import（audit-evasion）、kill_switch:11 KILL_SWITCH_ACTIVATIONS/STEP_FAILURES、execution/engine:25 ORDER_LATENCY/ORDERS_FILLED/ORDERS_TOTAL 全部改走 self._sink.record_*（commit b2a4cf8，Protocol 扩展 6 个 record 方法）。L1-L5 现零 monitoring/ 直接 import。

**drift-realign 2026-07-28 更新（ISS-20260723-011 Protocol 扩展）**: MonitoringSink Protocol 方法数演进：ISS-019 基线 4 个 record（signal/bar_latency/signal_latency/portfolio）+ send_alert + start；ISS-044 +6（risk_event/kill_switch_activation/kill_switch_step_failure/order_total/order_filled/order_latency）；ISS-011 +4（gateway_connected/gateway_disconnect/gateway_reconnect/order_timed_out）→ 合计 **14 个 record_* + send_alert + start**。ISS-011 新增 2 L5 接入站点：`okx_gateway.py`（gateway connected/disconnect/reconnect 经 `_record_disconnect` helper）+ `order_manager.py`（check_timeouts 发 record_order_timed_out），背书 4 新 prometheus（GATEWAY_CONNECTED gauge + GATEWAY_DISCONNECTS/GATEWAY_RECONNECTS/ORDERS_TIMED_OUT counters）。risk_engine rejection log 加 details+symbol。

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

<spec-entry category="coding" keywords="config-sourced,hardcoded-fallback,baseline,yaml-schema-drift,position-sizer,iss-012" date="2026-07-28" sid="S-20260728-iu1x" title="config-sourced hardcoded fallback MUST 保 byte-for-byte backtest baseline" description="hardcoded fallback 迁移 config 时默认值必须 byte-for-byte 对齐保 baseline" source="main@f6021c0">

### config-sourced hardcoded fallback MUST 保 byte-for-byte backtest baseline

当 hardcoded 默认值迁移到 Pydantic config 字段时，字段默认值必须与原硬编码完全相等（如 0.10/10.0/0.001），保 backtest baseline 不变；S1（pydantic 字段）+ S2（default.yaml 键）同 commit 落地以满足 TestConfigSchemaDrift 守卫；fee 等已有 single-source-of-truth 字段复用而非新建（D3）。这是 YAML-schema-drift 防护的通则实例（前序 validate_symbol / TestConfigSchemaDrift）。范本：ISS-012 PositionSizer (commit 8ffd612) — fixed_pct/min_order_notional 落 RiskConfig，fee_rate 复用 ExecutionConfig.taker_fee；守卫 test_config_sourced_defaults + TestConfigSchemaDrift。

</spec-entry>

<spec-entry category="coding" keywords="credential-redaction,cwe-532,redact-secrets,fail-closed,typer-badparameter,reg-1,cli,choke-point" date="2026-07-28" sid="S-20260728-q1ha" title="Credential redaction choke-point + fail-closed re-raise ordering (REG-1)" description="redact_secrets 公开 choke-point + typer.BadParameter 在 except Exception 前 raise" source="main@f6021c0">

### Credential redaction choke-point + fail-closed re-raise ordering (REG-1)

所有面向用户/日志/快照的异常字符串经 common/redaction.py redact_secrets() 脱敏（CWE-532）；redact_secrets 是公开 API（非 _redact），对齐 arch security-primitive 公开契约。CLI except Exception 路径必经 redact_secrets(str(e)) 再输出。FAIL-CLOSED 例外：配置校验类错误（typer.BadParameter / 缺 env vars / click.ClickException）须在通用 except Exception 前 except: raise 传播到框架 exit handler（非零 exit + usage message），不可被 redact 吞成 exit 0。这是 fail-silent antipattern（S-20260724-elsu）的 CLI analog — exit 0 是合法 success 值，不可复用为错误路径返回。范本：cli/main.py run _run_session（H3 模块级 import redact_secrets + REG-1 加 except typer.BadParameter: raise 在 except Exception 前，commit 4e32c24+74b83d1）。

</spec-entry>

<spec-entry category="coding" keywords="flush-signals,GIL,原子操作,to-thread,emit-signal,线程安全" date="2026-07-31" sid="S-20260731-c4n5" title="flush_signals 引用交换是 CPython GIL 级别的原子操作，无需显式锁" description="to_thread 工作线程的 emit_signal 与主协程的 flush_signals 之间依赖 GIL 原子性" source="phase-6-codereview">

### flush_signals 引用交换的 GIL 原子性契约

`StrategyContext.flush_signals()` 使用引用交换模式：`signals, self._signals = self._signals, []`。这是一个单条字节码级别的赋值操作，在 CPython GIL 下是原子的。

**线程安全模型**：`on_bar` 经 `asyncio.to_thread` 在工作线程中执行，调用 `ctx.emit_signal(signal)` 向 `self._signals` 列表追加。主协程在 `to_thread` future 完成后调用 `ctx.flush_signals()` 清空列表。由于：
1. `list.append()` 在 CPython 下是单条字节码操作（GIL 原子）
2. `flush_signals` 的引用交换是单条赋值（GIL 原子）
3. `to_thread` 保证 `flush_signals` 在所有 worker 线程的 `emit_signal` 完成后才执行

因此无需显式锁（`threading.Lock`）。这是 CPython 特有的线程安全保证，不可移植到 PyPy/Jython。

**禁止修改**：不可将 `flush_signals` 改为 copy-then-clear（如 `signals = list(self._signals); self._signals.clear()`），这会丢失原子性（两步操作之间可能被 `emit_signal` 插入）。也不可添加显式锁（增加复杂度且无必要）。

落地：`quantflow/strategy/base.py` `StrategyContext.flush_signals`。测试：`tests/unit/test_m4_killswitch_threadflush.py` `TestFlushSignalsAtomic` + `TestConcurrentEmitSignal`（50 线程并发 emit + 双 context 隔离）。
</spec-entry>

<spec-entry category="coding" keywords="hot-path,zero-alloc,deque,tuple,cache,per-bar,per-signal,performance" date="2026-08-01" sid="S-20260801-a3f1" title="热路径零分配：per-bar/per-signal 管线用 tuple+deque(maxlen)+缓存" description="风控/信号管线每 bar 执行函数：bound-method tuple 在 __init__ 构建 + deque(maxlen) + 纯函数按失效键缓存" source="harvest:20260723-trade-main-path">

### 热路径零分配模式

每 bar/信号执行管线（如 `risk_engine.check()`）禁止每次调用分配新 list/做切片/重算纯函数。

**三条规则**：
1. **bound-method tuple**：检查链在 `__init__` 一次性构建为 `tuple`（不可变，零 per-call 分配），不用 `list`
2. **deque(maxlen=N)**：滑动窗口用 `collections.deque(maxlen=N)`（O(1) 自动驱逐），不用 `list + [-N:]` 切片（O(n) 复制）
3. **纯函数缓存**：`np.percentile` 等重算函数按失效键（如 history len）缓存，len 变化才重算

**检测方法**：定位每 bar 调用函数 → 检查内部 `new list` / 切片 / 重算 → 改为 `__init__` 构建 + 缓存。

落地：`quantflow/signal/risk_engine.py` — `_checks` tuple + `deque(maxlen=500)` + VaR 缓存 keyed on history len。
</spec-entry>

<spec-entry category="coding" keywords="state-machine,order,timeout,terminal,partial-fill,cancelled,guard" date="2026-08-01" sid="S-20260801-b7e2" title="订单状态机完整性：timeout 标 terminal+撤单+返回值不弃+terminal guard+partial 建模" description="订单 timeout 必须标 CANCELLED terminal + 触发撤单；update() 加 terminal guard；PARTIAL 状态建模" source="harvest:20260723-trade-main-path">

### 订单生命周期状态机完整性

**四条规则**：
1. **timeout 标 terminal**：`check_timeouts()` 必须将超时订单 `status` 改为 `CANCELLED`（terminal），不可仅 pop 内部 pending dict
2. **返回值触发撤单**：`check_timeouts()` 返回 `(id, symbol)` 列表，调用方必须用于触发 `gateway.cancel_order`，返回值不可丢弃
3. **terminal guard**：`update()` 方法检查 `order.status in TERMINAL` 后拒绝覆盖，防止 late fill 覆盖 timeout 状态
4. **PARTIAL 建模**：`filled > 0 且 < quantity` 时设 `PARTIAL` 状态并留 pending，不可直接跳到 FILLED 丢部分成交

**检测方法**：状态机遍历 SUBMITTED→PARTIAL→FILLED / →CANCELLED / →REJECTED，检查每条转换是否更新 status + 触发副作用。

落地：`quantflow/execution/order_manager.py` — terminal guard + PARTIAL + check_timeouts 返回契约。
</spec-entry>