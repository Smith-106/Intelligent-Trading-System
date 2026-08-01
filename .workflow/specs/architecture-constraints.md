---
title: "Architecture Constraints"
readMode: required
priority: high
category: arch
keywords:
  - architecture
  - module
  - layer
  - boundary
  - dependency
  - structure
---

# Architecture Constraints

Auto-generated from project structure. Update manually as architecture evolves.

## Module Structure
- Type: single-package (quantflow/)
- Key modules:
  - quantflow/data/ — 数据获取、清洗、存储 (L1)
  - quantflow/indicators/ — 21 个因子、注册表、指标引擎 (L2)
  - quantflow/strategy/ — 策略基类、回测、优化、验证 (L3)
  - quantflow/signal/ — 信号生成、风险引擎、仓位调整 (L4)
  - quantflow/execution/ — 网关、执行引擎、订单管理、OrderRouter (L5)。ExecutionEngine 保留 gateway 生命周期 + submit 编排(kill_switch→route→track→metric→event→fill);OrderRouter (ISS-003) 拥有 gateway dispatch + Order/Request 构造。
  - quantflow/monitoring/ — Prometheus 指标、告警 (L6)
  - quantflow/common/ — 共享数据模型、事件总线、配置
  - quantflow/cli/ — Typer + Rich CLI

## Layer Boundaries
- 单向依赖：低层不导入高层
- common 是基础层（被所有层导入）
- data → common (不导入更高层)
- indicators → common (独立于 data)
- strategy → common + indicators
- signal → common
- execution → common（monitoring 经 `common/monitoring_sink.py` 的 MonitoringSink Protocol 注入，lower layer 不 import `monitoring/`；见 §181 详述。drift-realign DFT-2f9a4c71 修正，2026-07-26）
- strategy.engine (TradingSession) 是编排器，导入所有层
- cli → 所有层（延迟导入以加快启动）

## Dependency Rules
- 禁止跨层直接导入（必须通过 common 或显式接口）
- TradingSession 是唯一允许跨层编排的类

## Technology Constraints
- Runtime: Python >= 3.11
- Module system: standard Python package (pyproject.toml + hatchling)
- Strict mode: mypy strict = true, python_version = "3.11"

## Entries

<spec-entry category="arch" keywords="generate_signals,on_bar,增量,向量化,双模式API" date="2026-06-13" title="保持 generate_signals(df) 为研究 API，增量 live/paper 用 on_bar" description="策略双模式 API 设计决策">
### 保持 generate_signals(df) 为研究 API，增量 live/paper 用 on_bar

保持 `generate_signals(df)` 作为向量化研究/回测 API 不变，为 live/paper 添加增量 `on_bar()` 路径。增量路径使用 bounded deque + rolling state，避免每根 bar 重建 DataFrame。必须证明增量信号与向量化信号 parity。

**来源**: ANL-001 性能分析 (context.md Decision 3 + locked constraint)
**验收**: 增量 vs 向量化信号 parity 测试存在，3 个真实策略达 2000 bars/s
</spec-entry>

<spec-entry category="arch" keywords="策略顺序,波动率突破,资金费率,动量轮动,ML集成,实施优先级" date="2026-06-13" title="新增策略实施顺序" description="从 brainstorm 收敛的四策略优先级">
### 新增策略实施顺序

新增策略按优先级排序：P1 波动率突破（复杂度低、互补性强）→ P2 资金费率（Crypto 特有、简单有效）→ P3 动量因子轮动（需多品种支持）→ P4 ML 集成（高工作量）。跨交易所套利因架构改动大优先级最低。

**来源**: brainstorm-strategies (brainstorm-output.md)
**理由**: P1/P2 复杂度低且互补性强，可并行实现
</spec-entry>

<spec-entry category="arch" keywords="W3铁律,双模式,回顾模式,渐进模式,波浪理论" date="2026-06-13" title="W3 铁律双模式" description="浪3不能最短铁律的实时处理方案">
### W3 铁律双模式：回顾强制、渐进仅检查不拒绝

回顾模式（RETROSPECTIVE）：W3 不能最短铁律强制执行，违反即拒绝浪型分类。
渐进模式（PROGRESSIVE）：W3 运行中仅检查+警告，不拒绝分类。

**来源**: brainstorm-elliott-wave C-001 决议
**理由**: Q2 滞后判定 + Q3 实时困难，需平衡严谨与可用性
</spec-entry>

<spec-entry category="arch" keywords="背离检测,浪级比较,WaveCount,DivergenceDetector" date="2026-06-13" title="DivergenceDetector 强制浪级比较" description="背离检测接口必须基于 WaveCount">
### DivergenceDetector 强制浪级比较

`DivergenceDetector.detect(wave_count: WaveCount)` — 接口接收 WaveCount 而非裸 pivots，强制 W5 vs W3 浪级比较。顶背离：W5 价格新高但 MACD 未新高。底背离：W2/W4 价格新低但 MACD 未新低。

**来源**: brainstorm-elliott-wave C-003 决议
**理由**: 波浪理论背离验证必须基于浪级，通用 pivots 接口会导致误用
</spec-entry>

<spec-entry category="arch" keywords="仓位管理,RiskEngine,PositionRequest,风控权限" date="2026-06-13" title="ScalingPosition → RiskEngine: PositionRequest 权限控制" description="分批建仓与风控引擎的交互协议">
### ScalingPosition → RiskEngine 交互协议（⚠️ ISS-20260723-004 已删 ScalingPositionSizer 死代码，本 spec-entry 的交互协议 moot）

ScalingPositionSizer 输出 `PositionRequest`，由 RiskEngine 做最终权限控制。单笔风险 ≤2%，日最大亏损 ≤5%，月最大亏损 ≤15%。RiskEngine 可拒绝或缩减 PositionRequest。

**来源**: brainstorm-elliott-wave G-003 缺口补充
**理由**: 分批建仓模型需与风控体系解耦，RiskEngine 是最终权限门

**drift-realign 2026-07-28 标注**: ScalingPositionSizer/PositionRequest/ScalingConfig/PositionPhase 4 类已随 ISS-004 (commit a5b7f37) 删除（生产零引用死代码）。当前仓位 sizing 由 `signal/position_sizer.py` PositionSizer 直接产出 notional（half-Kelly + vol-target + 单名上限 min 下界）。单笔 ≤2%/日 ≤5%/月 ≤15% 约束现由 PositionSizer.size 内执行。若未来重启分批建仓，应作新 spec 而非恢复本 stale 引用。
</spec-entry>

<spec-entry category="arch" keywords="波浪理论,六层架构,规则引擎,集成方式" date="2026-06-13" title="波浪理论集成到 QuantFlow 六层架构" description="波浪理论系统设计决策">
### 波浪理论集成到 QuantFlow 六层架构，纯规则引擎

- 集成方式：集成到 QuantFlow 六层架构（非独立系统），复用现有基础设施
- 量化方式：纯规则引擎（非 ML 混合），可回测可验证，解决"千人千浪"
- 浪型表示：枚举状态机，与三大铁律规则逻辑一致
- 多时间框架：复用现有 fetcher + MTF 对齐逻辑

**来源**: brainstorm-elliott-wave D1/D2/D3 决策
**理由**: 复用六层架构降低实现成本；规则引擎确保可验证性；状态机与铁律逻辑一致
</spec-entry>

<spec-entry category="arch" keywords="security-primitive,private-helper,common-module,public-api,choke-point" date="2026-07-05" title="Cross-cutting security primitives are public API in quantflow/common/, never private borrow-ins" description="Validation/auth choke points imported across layers must be public, not underscored module-private helpers">
### Cross-cutting security primitives are public API in quantflow/common/, never private borrow-ins

A security choke point (symbol validation, auth/CSRF policy) imported by 2+ modules MUST be a public (no underscore) function in a dedicated `quantflow/common/` (or `quantflow/web/security.py`) module. The underscore signals "module-private implementation detail" — the wrong contract for a security primitive imported across layers.

Anti-pattern: `_validate_symbol` defined private in `data/store.py` and lazy-imported via `from quantflow.data.store import _validate_symbol` inside methods of `data/fetcher.py` + `data/feature_store.py`; auth/CSRF middleware as private functions in the routing module `web/app.py`.

Why: (1) inconsistent audit surface — callers may re-implement instead of importing, bypassing the invariant; (2) the borrowing module's import breaks silently if the underscore form is renamed; (3) security review can't grep for a single public API.

Closing pattern: `quantflow/common/validators.py` exposes public `validate_symbol`/`validate_columns` + `SYMBOL_PATTERN`/`COLUMN_PATTERN`; `quantflow/web/security.py` exposes `same_origin_guard`/`_station_token`/`is_loopback_host`; `quantflow/common/redaction.py` exposes public `redact_secrets` (CWE-532 credential choke-point). Back-compat aliases kept at old sites only when tests import the underscored form.

**Web-layer XSS choke-point (ISS-UX-20260728, commit 4e32c24)**: the same single-audit-face discipline applies to `innerHTML` on the frontend — `quantflow/web/static/app.js` exposes `setHTML(node, html)` as the ONLY sanctioned `innerHTML` sink; `metricCard` string/label branches escape via `escapeHtml` before reaching `setHTML`. Static guard `tests/unit/test_innerhtml_choke_point.py` greps `app.js` source to assert `setHTML` exists + escape wrap (mirrors the `validate_symbol` single-audit-face pattern). Server/user-interpolated text MUST be pre-escaped — `setHTML` does not auto-escape (unlike `textContent`, which is the M4-safe path for non-HTML dynamic text, e.g. the bootstrap overlay retry button).

Source: odyssey-review security-fixes session (REV-005, REV-013).
</spec-entry>

<spec-entry category="arch" keywords="launch-guard,bind-boundary,create-app,run-station,fail-closed" date="2026-07-05" title="Launch-time safety guards live at the bind boundary, documented in the constructor docstring" description="When a fail-closed guard depends on a bind-time param, keep it at the launcher; document the contract in the app-constructor docstring">
### Launch-time safety guards live at the bind boundary, documented in the constructor docstring

When a fail-closed launch guard (e.g. "non-loopback bind requires an auth token") depends on a parameter the app constructor does NOT receive (the bind `host`), keep the guard at the bind boundary (`run_station`) — the only entry point that knows the host. Do NOT force the parameter into the constructor to "share" the guard: that breaks the test harness, which calls `create_app()` directly and assumes a loopback-equivalent threat model.

Contract: the app-constructor docstring MUST state that the guard is enforced at the bind boundary and why (host is not a constructor param). The guard logic itself should be a reusable helper (e.g. `is_loopback_host(host)` + `_station_token()`) callable from the launcher, not inlined.

Closing pattern: `web/app.py` `run_station` enforces `if not is_loopback_host(host) and not _station_token(): raise RuntimeError(...)`; `create_app` docstring documents the contract. Tests construct `create_app()` directly (host-agnostic).

Source: odyssey-review security-fixes session (REV-006).
</spec-entry>


<spec-entry category="arch" keywords="llm因子挖掘,schema-only,防泄漏,rd-agent,时间点安全" date="2026-07-18" sid="S-20260718-cxia" title="LLM 因子挖掘须采纳 schema-only 数据中心设计防泄漏" description="LLM 因子挖掘只接触 schema 级信息,不接触原始数据与时间分割,防未来数据泄漏" source="harvest:deep-research-20260718">

### LLM 因子挖掘须采纳 schema-only 数据中心设计防泄漏

引入 LLM 驱动因子挖掘(如规划中的 Qlib RD-Agent)时,LLM 从不接触原始市场数据或显式时间分割,只接触 schema 级信息(列名/类型/统计概要),从而防止信息泄漏。这是 Microsoft RD-Agent(Q)(NeurIPS 2025, arXiv:2505.15155 Section 4)的核心设计原则,直接对应 QuantFlow 时间点安全查询/防未来数据泄漏要求——隐藏时间分割边界正是针对同一泄漏向量。落地时需新建 schema 暴露层屏蔽原始市场数据与 train/val/test 时间分割边界,LLM 只看到 schema 不看到数据值与时间点。来源: deep-research-20260718 F6/F7 (3-0 verified)。注: RD-Agent 2x ARR 基准为 medium(2-1),实验在股票市场跨资产泛化未直接验证,仅作架构范式参考。

</spec-entry>

<spec-entry category="arch" keywords="回测实盘一致,parity,tradingsession,事件驱动,确定性时钟" date="2026-07-18" sid="S-20260718-h6ml" title="回测-实盘 parity 范式:同语义执行+同确定性时钟,策略研究到生产不改代码" description="回测与实盘共用同语义执行+同确定性时钟,策略研究到生产不改代码" source="harvest:deep-research-20260718">

### 回测-实盘 parity 范式:同语义执行+同确定性时钟,策略研究到生产不改代码

TradingSession 统一 backtest/paper/live 的目标可参照两个成熟范式:(1) NautilusTrader 用 Rust 核心(71.3% Rust/22.4% Python)+mimalloc+tokio+PyO3,Python 仅作控制面,回测与实盘共用同一确定性事件驱动执行语义与时钟,策略部署无需改代码;(2) Jesse 用单一 Strategy 类跨 backtest/live/paper/optimize/benchmark 保持相同方法签名(should_long/go_long/before/hyperparameters),模式由运行时探测(jh.is_live())而非切换类。QuantFlow 需审计 TradingSession 与 PaperGateway/OKXGateway 代码路径是否真正等价(无模式间分支)。Backtrader 也是单一 Cerebro 编排回测+实盘的范式,但已基本停止维护,仅作架构参照不作实盘依赖。来源: deep-research-20260718 F11/F12 (3-0 verified)。

**drift-realign 2026-07-28 更新（ISS-20260723-005 market_type 双分支）**: OKXGateway 引入 `market_type` ctor 参数（默认 `spot`），`query_positions` 显式 spot/swap 双分支 — `_query_swap_positions` 读 contracts schema、`_query_spot_positions` 从 `fetch_balance` 派生非 quote 资产（entry_price=0/unrealized_pnl=0，spot 无杠杆）。这使 parity 声称"无模式间分支"需收窄：paper/live **spot-mode** parity 成立（PaperGateway spot 语义与 OKXGateway spot 分支对齐）；**swap-mode** 需 PaperGateway 补 swap 分支或文档标注限制（当前 PaperGateway 无 market_type 分支，仅 spot 语义）。parity 审计需区分 market_type 而非笼统称等价。

</spec-entry>

<spec-entry category="arch" keywords="跨交易所套利,统计套利,价差z-score,half-life,市场中性" date="2026-07-20" sid="S-20260720-5v13" title="跨交易所套利策略候选（P5，未实现）——brainstorm 20260602 收敛的 5 候选中唯一未落地项。核心逻辑：同一交易对在不同交易所的价差 → 统计套利。指标：价差 Z-Score、Half-Life、Hedge Ratio（OLS/Kalman）。互补性：市场中性，不依赖方向，与所有方向性策略负相关。复杂度：高（需多交易所数据源 + 低延迟执行）。适用：全状态。学术依据：Avellaneda &amp; Lee (2010) 统计套利。优先级最低因架构改动大（需多 Gateway 数据源 + 低延迟执行路径），暂未实现。设计依据详见 knowhow DOC-strategy-matrix-complementarity-and-rationale。" description="brainstorm 5 候选中唯一未落地项——市场中性统计套利" source="main@805e5b7">

### 跨交易所套利策略候选（P5，未实现）——brainstorm 20260602 收敛的 5 候选中唯一未落地项。核心逻辑：同一交易对在不同交易所的价差 → 统计套利。指标：价差 Z-Score、Half-Life、Hedge Ratio（OLS/Kalman）。互补性：市场中性，不依赖方向，与所有方向性策略负相关。复杂度：高（需多交易所数据源 + 低延迟执行）。适用：全状态。学术依据：Avellaneda & Lee (2010) 统计套利。优先级最低因架构改动大（需多 Gateway 数据源 + 低延迟执行路径），暂未实现。设计依据详见 knowhow DOC-strategy-matrix-complementarity-and-rationale。



</spec-entry>

<spec-entry category="arch" keywords="parity,backtest,BacktestEngine,paper,live,独立引擎" date="2026-07-22" sid="S-20260722-pd2y" title="backtest 不在 parity 范围 — parity 仅约束 paper/live 路径" description="parity spec 称 backtest/paper/live 共享语义，但 backtest 走独立 BacktestEngine，parity 仅 paper/live 成立；不可宣称三方一致" source="harvest:deepresearch-20260718">

### backtest 不在 parity 范围 — parity 仅约束 paper/live 路径

「策略 backtest/paper/live 三模式语义一致」的 parity 声称 MUST 精确界定范围：paper 与 live 共享  +  + 同一  抽象，parity 严格成立；但 **backtest 走独立 （纯 pandas/numpy 向量化，不经 ExecutionEngine/PositionManager 的 cash/position book）**，三方不共享同一执行路径，因此 parity 不覆盖 backtest。

架构含义：
1. 不可基于「三模式一致」的前提在 backtest 中复用 paper/live 的 PortfolioManager/PositionManager book 假设——backtest 的 cash/position 由 BacktestEngine 自治。
2. 评估 parity regression（如 ISS-20260720-004 多 book reconcile）时，修复范围限定 paper↔live 两个 L4/L5 book，backtest 的独立 book 不在 reconcile 范围。
3. 新增影响执行路径的特性时，若声称「backtest 也能验证」，必须显式说明该特性在 BacktestEngine 中是否有等价实现，不可默认继承。

发现来源：deep-research-20260718 insight F7（grill 矛盾经源码核实成立）——backtest.py:1-4 注释 + engine.py:46 vs research session 独立路径。本次 harvest 收割为 arch constraint。
</spec-entry>


<spec-entry category="arch" keywords="layer-violation,lazy-import,monitoring-coupling,l6,audit-evasion,architecture" date="2026-07-24" sid="S-20260724-02ek" title="L6 跨层耦合禁用 in-function import 规避审计" description="L6 跨层耦合禁用；in-function import 规避静态审计是反模式；guard 须扫两层" source="main@bb3c6cd">

### L6 跨层耦合禁用 in-function import 规避审计

低下层（L3 strategy/engine、L4 signal/risk_engine:90、L5 execution/kill_switch+engine、web/session_manager）不得 import monitoring/（L6）具体类——违反事件驱动 L6 契约（L6 应订阅 EventBus，低下层只 publish）。特别禁止用 in-function 延迟 import（risk_engine.py:90 把 monitoring import 放函数体内）来躲过 top-level grep 'import monitoring' 静态扫描——这是 audit-evasion 反模式，lazy import 只可用于打破循环依赖，不可用于规避分层审计。修复：全部 monitoring 调用移到 L6 EventBus subscriber；若必须同步推指标，在 common/ 暴露 thin Protocol 并注入。L6 耦合的静态 guard 必须同时扫 top-level + in-function import。

**arch-013 落地站点（drift-realign 2026-07-28 更新）**: ISS-019/044 落地 4 站点（strategy/engine、risk_engine、execution/engine+kill_switch）；ISS-20260723-011 扩展 2 新站点 — `okx_gateway.py`（record_gateway_connected/disconnect/reconnect 经 `_record_disconnect` helper）+ `order_manager.py`（record_order_timed_out 在 check_timeouts），均经 `common/monitoring_sink.py` Protocol 注入（ctor `monitoring_sink` 参数，默认 NullMonitoringSink），不直接 import `quantflow.monitoring.*`。Protocol 12→16 方法。

</spec-entry>

<spec-entry category="arch" keywords="l4,权威账本,engine.submit,薄路由,reconcile,paper-live-parity" date="2026-07-25" sid="S-20260725-y8sf" title="L4 单一权威账本: engine.submit 统一负责 L4 PortfolioManager 的 fill 更新(含 fee), _process_signal 不再二次更新 L4。L5 PositionManager 退化为薄路由委托 L4(全 9 方法委托), PaperGateway 移除第三套 _cash 账本(仅保留 _positions 作为 gateway 本地交易所视图, 与 OKXGateway 对称: gateway 暴露交易所持仓视图不拥有 L4 账本)。消除 L5 委托 L4 后 engine.submit + _process_signal 双计同一 fill 的风险。fee 由 L4 单次扣除(PaperGateway send_order 不再借记 cash)。paper/live parity: 两者均经 engine.submit 单一 L4 fill 更新点。backtest 独立向量化 book 不在 reconcile 范围(per arch parity spec)。" description="多 book reconcile: L4 单一权威账本 + L5 薄路由委托 + engine.submit 统一 fill 更新" source="main@06a8d93">

### L4 单一权威账本: engine.submit 统一负责 L4 PortfolioManager 的 fill 更新(含 fee), _process_signal 不再二次更新 L4。L5 PositionManager 退化为薄路由委托 L4(全 9 方法委托), PaperGateway 移除第三套 _cash 账本(仅保留 _positions 作为 gateway 本地交易所视图, 与 OKXGateway 对称: gateway 暴露交易所持仓视图不拥有 L4 账本)。消除 L5 委托 L4 后 engine.submit + _process_signal 双计同一 fill 的风险。fee 由 L4 单次扣除(PaperGateway send_order 不再借记 cash)。paper/live parity: 两者均经 engine.submit 单一 L4 fill 更新点。backtest 独立向量化 book 不在 reconcile 范围(per arch parity spec)。



</spec-entry>

<spec-entry category="arch" keywords="翻仓,realized-pnl,归因,cash-解耦,closing-qty" date="2026-07-25" sid="S-20260725-nxzl" title="翻仓 realized PnL 归因与 cash 解耦(保守路径): PortfolioManager.update_position 在 cash mutation 后, 当 existing.quantity * quantity_delta &lt; 0(方向反转/部分平仓) 时, 用 closing_qty = min(|delta|, |existing.qty|), sign = sign(existing.quantity), realized = (price - entry) * closing_qty * sign 累计到 _realized_pnl。cash mutation 保留原 notional 语义(cash 总变动 = delta*price + fee), realized 仅作归因累计不重算 cash。0 数值回归(现有 cash 断言全保持), realized 可观测(snapshot 暴露 realized_pnl)。比重算 cash 方案更稳, 避免新 leg qty 代数推导风险。" description="翻仓 realized 归因: closing_qty*sign 累计, cash 保留原 notional 语义" source="main@06a8d93">

### 翻仓 realized PnL 归因与 cash 解耦(保守路径): PortfolioManager.update_position 在 cash mutation 后, 当 existing.quantity * quantity_delta < 0(方向反转/部分平仓) 时, 用 closing_qty = min(|delta|, |existing.qty|), sign = sign(existing.quantity), realized = (price - entry) * closing_qty * sign 累计到 _realized_pnl。cash mutation 保留原 notional 语义(cash 总变动 = delta*price + fee), realized 仅作归因累计不重算 cash。0 数值回归(现有 cash 断言全保持), realized 可观测(snapshot 暴露 realized_pnl)。比重算 cash 方案更稳, 避免新 leg qty 代数推导风险。



</spec-entry>

<spec-entry category="arch" keywords="partial-fill,cumulative,applied-filled-qty,增量,delta,双计" date="2026-07-25" sid="S-20260725-ue4p" title="partial-fill cumulative-fill 契约: ccxt/OKX 的 order['filled'] 是累计总量(非每次回调 delta)。Order.applied_filled_qty 跟踪已应用到 L4 的累计量, ExecutionEngine.submit 派生增量 delta = filled_quantity - applied_filled_qty, 仅当 delta &gt; POSITION_EPSILON 时调 L4 update_position(qty_signed=delta*side, fee=order.fee), 然后 applied_filled_qty = filled_quantity。POSITION_EPSILON guard 防 delta=0 重复回调误调 L4。OKXGateway.send_order 从 ccxt result 提取 filled/average/fee.cost 累计值盖印到 order。OKX REST create_order 仅返回 market order final state; limit 部分成交的 live 自动感知需未来 ws(watch_orders)集成。" description="cumulative-fill 契约: applied_filled_qty 防 partial 重复 fill 双计" source="main@06a8d93">

### partial-fill cumulative-fill 契约: ccxt/OKX 的 order['filled'] 是累计总量(非每次回调 delta)。Order.applied_filled_qty 跟踪已应用到 L4 的累计量, ExecutionEngine.submit 派生增量 delta = filled_quantity - applied_filled_qty, 仅当 delta > POSITION_EPSILON 时调 L4 update_position(qty_signed=delta*side, fee=order.fee), 然后 applied_filled_qty = filled_quantity。POSITION_EPSILON guard 防 delta=0 重复回调误调 L4。OKXGateway.send_order 从 ccxt result 提取 filled/average/fee.cost 累计值盖印到 order。OKX REST create_order 仅返回 market order final state; limit 部分成交的 live 自动感知需未来 ws(watch_orders)集成。



</spec-entry>

<spec-entry category="arch" keywords="构造顺序,懒绑定,set-portfolio,循环依赖,l4-l5" date="2026-07-25" sid="S-20260725-0du3" title="构造顺序循环懒绑定: ExecutionEngine 在 PortfolioManager 之前构造(TradingSession line 130 前注入 gateway), 产生 L4 引用循环。解法: ExecutionEngine.__init__ 接受 portfolio=None, PositionManager 默认自建私有 PortfolioManager(standalone/test 可用); set_portfolio(portfolio) 在 PortfolioManager 构造后注入共享 L4, 内部调 position_mgr.bind_portfolio(portfolio) 重绑委托目标。Idempotent。PositionManager 默认自建 L4 保证 submit() 在 standalone/test 不崩。" description="构造顺序循环: set_portfolio 懒绑定重绑共享 L4" source="main@06a8d93">

### 构造顺序循环懒绑定: ExecutionEngine 在 PortfolioManager 之前构造(TradingSession line 130 前注入 gateway), 产生 L4 引用循环。解法: ExecutionEngine.__init__ 接受 portfolio=None, PositionManager 默认自建私有 PortfolioManager(standalone/test 可用); set_portfolio(portfolio) 在 PortfolioManager 构造后注入共享 L4, 内部调 position_mgr.bind_portfolio(portfolio) 重绑委托目标。Idempotent。PositionManager 默认自建 L4 保证 submit() 在 standalone/test 不崩。

**arch-017 同构站点（drift-realign 2026-07-28）**: ISS-20260723-003 (commit c51d571) 的 `OrderRouter.set_gateway` 采用同一 lazy-binding 模式 — router 构造时 `gateway=None`（因 ExecutionEngine.start() 后才建 gateway），start() 调 `router.set_gateway(self._gateway)` 重绑。route() 在未绑定时 raise "Gateway not initialized — call start() first"，与 set_portfolio 未注入时 PositionManager 默认自建 L4 不崩的兜底语义对称。arch-017 = 构造序在前的组件接受 None + 后置 set_* 重绑共享引用。



</spec-entry>

<spec-entry category="arch" keywords="daily-loss,total-value,baseline,日切锚定,warmup-guard" date="2026-07-25" sid="S-20260725-58tc" title="daily_loss 门 total-vs-baseline 语义: RiskEngine._check_daily_loss 改用 pnl_pct = (portfolio.total_value - portfolio.daily_baseline) / daily_baseline, baseline&lt;=0 时 warmup guard 返回 passed=True(首日无 baseline 不阻断)。daily_baseline 由 TradingSession.on_bar 日切锚定: current_day = bar.timestamp // 86_400_000(UTC 日历日索引), 新日时 portfolio.set_daily_baseline(curr_equity)。daily_baseline 经 Portfolio dataclass 快照传递(非 RiskEngine 持 L4 引用绕过快照), 保持 check 纯函数语义。原 sum(unrealized_pnl)/total 语义被替代(不含 realized + 对浮亏过度敏感)。" description="daily_loss 改 total-vs-baseline + 日切锚定 + warmup guard" source="main@06a8d93">

### daily_loss 门 total-vs-baseline 语义: RiskEngine._check_daily_loss 改用 pnl_pct = (portfolio.total_value - portfolio.daily_baseline) / daily_baseline, baseline<=0 时 warmup guard 返回 passed=True(首日无 baseline 不阻断)。daily_baseline 由 TradingSession.on_bar 日切锚定: current_day = bar.timestamp // 86_400_000(UTC 日历日索引), 新日时 portfolio.set_daily_baseline(curr_equity)。daily_baseline 经 Portfolio dataclass 快照传递(非 RiskEngine 持 L4 引用绕过快照), 保持 check 纯函数语义。原 sum(unrealized_pnl)/total 语义被替代(不含 realized + 对浮亏过度敏感)。



</spec-entry>

<spec-entry category="arch" keywords="execution-engine,srp,god-object,order-router,route,build-order,close-position,arch-017" date="2026-07-27" sid="S-20260727-or3r" title="ExecutionEngine god-object 退役: OrderRouter 抽取 gateway dispatch + Order 构造, engine 保留 submit 编排 + gateway 生命周期 (ISS-20260723-003)" description="ExecutionEngine 原 7 职责 god-object; ISS-003 抽 OrderRouter 拿 routing + Order shaping + close_request, engine 降级为编排 facade" source="main@c51d571">

### ExecutionEngine god-object 退役 — OrderRouter 抽取 (ISS-20260723-003, commit c51d571)

ExecutionEngine 原持有 7 职责 (routing / order state / event publish / metric / Order construction / close_position / sync) 形成 god-object。ISS-003 将两个纯 order-construction 职责移入 `quantflow/execution/order_router.py` `OrderRouter`:
- `route(order) -> str` — gateway `send_order` dispatch（routing concern）
- `build_order(request) -> Order` — OrderRequest → Order 构造（params 副本，下游不 mutate caller request）
- `build_close_request(position) -> OrderRequest` — 对向平仓请求（reduceOnly=True，SEC-H2 防 flip）
- `is_closeable(position) -> bool` staticmethod — POSITION_EPSILON 守卫，单一"可平仓"定义
- `set_gateway(gateway)` — arch-017 lazy binding（构造 unbound，start() 后重绑）

ExecutionEngine 保留: gateway 生命周期 (start/stop/connect/disconnect) + submit 编排 (kill_switch gate → router.route → track → metric → event → `_handle_fill`)。close_position 用 `router.is_closeable` + `build_close_request` + `submit_order`。新增 `router` property。hot-path 控制流不变，无回归。

**验收**: tests/unit/test_order_router.py 9 测试（route dispatch / no-gateway raise / error propagation / set_gateway rebind / build_order copy / close_request long+short reduceOnly / is_closeable None+epsilon+nontrivial）。全量 1559 passed。

</spec-entry>

<spec-entry category="arch" keywords="四象限,timeout,Fail-Closed,CRITICAL,pending,sweeper,cancel,sync" date="2026-07-31" sid="S-20260731-b9m3" title="Timeout 四象限 Fail-Closed 矩阵：cancel×sync 双失败必须 HOLD pending + CRITICAL 告警" description="数据循环 timeout 处理的四象限决策矩阵，双失败时不 release + sweeper 兆底" source="phase-6-codereview">

### Timeout 四象限 Fail-Closed 矩阵

数据循环 timeout 处理（`run_data_loop` 中的 `check_timeouts()` 分支）必须遵循 cancel × sync 的四象限决策矩阵：

| Quadrant | cancel_ok | sync_ok | Action |
|---|---|---|---|
| A | True | True | release（双确认） |
| B | True | False | release（cancel 确认） |
| C | False | True | release（sync 确认） |
| D | False | False | **HOLD pending**（Fail-Closed） |

**Quadrant D 约束**：当 cancel 和 sync 均失败时，系统处于完全盲区——无法验证交易所实际状态。此时 MUST NOT release pending（否则可能导致持仓超限）。pending 保留在台账中，由 `sweep_stale_pending(120s)` 兆底清理，并 MUST 触发 `logger.critical()` 告警要求人工复核。

**Legacy 路径**：空 symbol 的 timeout entry → 立即 release（无需 cancel/sync 判断）。

**异常吞没**：cancel 抛异常 → cancel_ok 保持 False（不传播）；sync_positions 抛异常 → 经 `contextlib.suppress` 吞没，sync_ok 保持 False。这保证单个 timeout 失败不中断数据循环。

落地：`quantflow/strategy/engine.py` `run_data_loop` ~lines 766-788。测试：`tests/unit/test_m4_timeout_quadrant.py` 9 测试覆盖全四象限 + legacy + 异常 + 交互（D-hold 后下周期 sync 成功 → release）。
</spec-entry>