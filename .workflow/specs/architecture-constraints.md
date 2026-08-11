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
  - quantflow/execution/ — 网关、执行引擎、订单管理、OrderRouter (L5)。ExecutionEngine 保留 gateway 生命周期 + submit 编排(kill_switch→route→track→metric→event→fill);OrderRouter (ISS-003) 拥有 gateway dispatch + Order/Request 构造。GatewayBase 含 query_open_orders() 抽象方法（orphan order 检测）。
  - quantflow/reconciliation/ — 仓位/订单漂移检测与对账引擎 (L5.5)。ReconciliationEngine 后台循环 + AuditLogger HMAC 签名审计 + PositionSnapshot/Discrepancy 模型。
  - quantflow/monitoring/ — Prometheus 指标、告警 (L6)。AlertCategory (15 类) × AlertPriority (4 级) 分类路由。
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

<spec-entry category="arch" keywords="generate_signals,on_bar,增量,向量化,双模式API" date="2026-06-13" title="保持 generate_signals(df) 为研究 API，增量 live/paper 用 on_bar" description="策略双模式 API 设计决策" sid="S-legacy-94ab063e">
### 保持 generate_signals(df) 为研究 API，增量 live/paper 用 on_bar

保持 `generate_signals(df)` 作为向量化研究/回测 API 不变，为 live/paper 添加增量 `on_bar()` 路径。增量路径使用 bounded deque + rolling state，避免每根 bar 重建 DataFrame。必须证明增量信号与向量化信号 parity。

**来源**: ANL-001 性能分析 (context.md Decision 3 + locked constraint)
**验收**: 增量 vs 向量化信号 parity 测试存在，3 个真实策略达 2000 bars/s
</spec-entry>

<spec-entry category="arch" keywords="策略顺序,波动率突破,资金费率,动量轮动,ML集成,实施优先级" date="2026-06-13" title="新增策略实施顺序" description="从 brainstorm 收敛的四策略优先级" sid="S-legacy-7e5a7b8e">
### 新增策略实施顺序

新增策略按优先级排序：P1 波动率突破（复杂度低、互补性强）→ P2 资金费率（Crypto 特有、简单有效）→ P3 动量因子轮动（需多品种支持）→ P4 ML 集成（高工作量）。跨交易所套利因架构改动大优先级最低。

**来源**: brainstorm-strategies (brainstorm-output.md)
**理由**: P1/P2 复杂度低且互补性强，可并行实现
</spec-entry>

<spec-entry category="arch" keywords="W3铁律,双模式,回顾模式,渐进模式,波浪理论" date="2026-06-13" title="W3 铁律双模式" description="浪3不能最短铁律的实时处理方案" sid="S-legacy-55b14d75">
### W3 铁律双模式：回顾强制、渐进仅检查不拒绝

回顾模式（RETROSPECTIVE）：W3 不能最短铁律强制执行，违反即拒绝浪型分类。
渐进模式（PROGRESSIVE）：W3 运行中仅检查+警告，不拒绝分类。

**来源**: brainstorm-elliott-wave C-001 决议
**理由**: Q2 滞后判定 + Q3 实时困难，需平衡严谨与可用性
</spec-entry>

<spec-entry category="arch" keywords="背离检测,浪级比较,WaveCount,DivergenceDetector" date="2026-06-13" title="DivergenceDetector 强制浪级比较" description="背离检测接口必须基于 WaveCount" sid="S-legacy-e689eae2">
### DivergenceDetector 强制浪级比较

`DivergenceDetector.detect(wave_count: WaveCount)` — 接口接收 WaveCount 而非裸 pivots，强制 W5 vs W3 浪级比较。顶背离：W5 价格新高但 MACD 未新高。底背离：W2/W4 价格新低但 MACD 未新低。

**来源**: brainstorm-elliott-wave C-003 决议
**理由**: 波浪理论背离验证必须基于浪级，通用 pivots 接口会导致误用
</spec-entry>

<spec-entry category="arch" keywords="仓位管理,RiskEngine,PositionRequest,风控权限" date="2026-06-13" title="ScalingPosition → RiskEngine: PositionRequest 权限控制" description="分批建仓与风控引擎的交互协议" sid="S-legacy-cae8ed3d">
### ScalingPosition → RiskEngine 交互协议（⚠️ ISS-20260723-004 已删 ScalingPositionSizer 死代码，本 spec-entry 的交互协议 moot）

ScalingPositionSizer 输出 `PositionRequest`，由 RiskEngine 做最终权限控制。单笔风险 ≤2%，日最大亏损 ≤5%，月最大亏损 ≤15%。RiskEngine 可拒绝或缩减 PositionRequest。

**来源**: brainstorm-elliott-wave G-003 缺口补充
**理由**: 分批建仓模型需与风控体系解耦，RiskEngine 是最终权限门

**drift-realign 2026-07-28 标注**: ScalingPositionSizer/PositionRequest/ScalingConfig/PositionPhase 4 类已随 ISS-004 (commit a5b7f37) 删除（生产零引用死代码）。当前仓位 sizing 由 `signal/position_sizer.py` PositionSizer 直接产出 notional（half-Kelly + vol-target + 单名上限 min 下界）。单笔 ≤2%/日 ≤5%/月 ≤15% 约束现由 PositionSizer.size 内执行。若未来重启分批建仓，应作新 spec 而非恢复本 stale 引用。
</spec-entry>

<spec-entry category="arch" keywords="波浪理论,六层架构,规则引擎,集成方式" date="2026-06-13" title="波浪理论集成到 QuantFlow 六层架构" description="波浪理论系统设计决策" sid="S-legacy-3f2bf039">
### 波浪理论集成到 QuantFlow 六层架构，纯规则引擎

- 集成方式：集成到 QuantFlow 六层架构（非独立系统），复用现有基础设施
- 量化方式：纯规则引擎（非 ML 混合），可回测可验证，解决"千人千浪"
- 浪型表示：枚举状态机，与三大铁律规则逻辑一致
- 多时间框架：复用现有 fetcher + MTF 对齐逻辑

**来源**: brainstorm-elliott-wave D1/D2/D3 决策
**理由**: 复用六层架构降低实现成本；规则引擎确保可验证性；状态机与铁律逻辑一致
</spec-entry>

<spec-entry category="arch" keywords="security-primitive,private-helper,common-module,public-api,choke-point" date="2026-07-05" title="Cross-cutting security primitives are public API in quantflow/common/, never private borrow-ins" description="Validation/auth choke points imported across layers must be public, not underscored module-private helpers" sid="S-legacy-7b834936">
### Cross-cutting security primitives are public API in quantflow/common/, never private borrow-ins

A security choke point (symbol validation, auth/CSRF policy) imported by 2+ modules MUST be a public (no underscore) function in a dedicated `quantflow/common/` (or `quantflow/web/security.py`) module. The underscore signals "module-private implementation detail" — the wrong contract for a security primitive imported across layers.

Anti-pattern: `_validate_symbol` defined private in `data/store.py` and lazy-imported via `from quantflow.data.store import _validate_symbol` inside methods of `data/fetcher.py` + `data/feature_store.py`; auth/CSRF middleware as private functions in the routing module `web/app.py`.

Why: (1) inconsistent audit surface — callers may re-implement instead of importing, bypassing the invariant; (2) the borrowing module's import breaks silently if the underscore form is renamed; (3) security review can't grep for a single public API.

Closing pattern: `quantflow/common/validators.py` exposes public `validate_symbol`/`validate_columns` + `SYMBOL_PATTERN`/`COLUMN_PATTERN`; `quantflow/web/security.py` exposes `same_origin_guard`/`_station_token`/`is_loopback_host`; `quantflow/common/redaction.py` exposes public `redact_secrets` (CWE-532 credential choke-point). Back-compat aliases kept at old sites only when tests import the underscored form.

**Web-layer XSS choke-point (ISS-UX-20260728, commit 4e32c24)**: the same single-audit-face discipline applies to `innerHTML` on the frontend — `quantflow/web/static/app.js` exposes `setHTML(node, html)` as the ONLY sanctioned `innerHTML` sink; `metricCard` string/label branches escape via `escapeHtml` before reaching `setHTML`. Static guard `tests/unit/test_innerhtml_choke_point.py` greps `app.js` source to assert `setHTML` exists + escape wrap (mirrors the `validate_symbol` single-audit-face pattern). Server/user-interpolated text MUST be pre-escaped — `setHTML` does not auto-escape (unlike `textContent`, which is the M4-safe path for non-HTML dynamic text, e.g. the bootstrap overlay retry button).

Source: odyssey-review security-fixes session (REV-005, REV-013).
</spec-entry>

<spec-entry category="arch" keywords="launch-guard,bind-boundary,create-app,run-station,fail-closed" date="2026-07-05" title="Launch-time safety guards live at the bind boundary, documented in the constructor docstring" description="When a fail-closed guard depends on a bind-time param, keep it at the launcher; document the contract in the app-constructor docstring" sid="S-legacy-62fb9b81">
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

<spec-entry category="arch" keywords="getattr,private,cross-layer,encapsulation,public-accessor,shadow-book,single-source" date="2026-08-01" sid="S-20260801-c5d3" title="禁止跨层 getattr 私有属性 + 同域对象单一权威源" description="高层禁止 getattr(low_layer, \"_private\") 绕接口抓私有属性；同域对象禁止 N 类各自维护独立可变账本" source="harvest:20260723-trade-main-path">

### 禁止跨层 getattr 私有属性

**规则 1**: 高层禁止 `getattr(low_layer, "_private", None)` 绕接口抓私有属性。isinstance 守卫使失败静默——目标属性重命名后观察者静默不挂载（如 `session_manager` 抓 `_event_bus`，重命名后 observe 链断开但无报错）。必须由低层暴露 public accessor。

**规则 2**: 同一域对象（如 positions）禁止 N 个类各自维护独立可变账本（如 PaperGateway / PositionManager / PortfolioManager 三本账，avg-entry 公式逐字重复且分叉）。必须单一权威源，其余层持引用/view。

**检测方法**：
- `grep getattr\(.*,\s*"_` 跨层调用
- `grep self\._<domain> = {}` 看是否多类镜像同域对象

落地：trade-main-path odyssey 根因 D（三本账零对账）+ 根因 generalize 扫描（session_manager getattr `_event_bus` / `last_error`）。
</spec-entry>

<spec-entry category="arch" keywords="redis,fallback,degraded-mode,in-memory,graceful-degradation,state-store,dq-monitor" date="2026-08-02" sid="S-20260802-redis-fallback" title="Redis 依赖必须有 in-memory fallback 降级路径" description="任何依赖 Redis 的运行时组件必须实现透明降级到进程内存储，确保 Redis 不可用时核心功能不中断" source="harvest:ralph-v2-20260802-220000">

### Redis 依赖必须有 in-memory fallback 降级路径

**规则**: 任何依赖 Redis 的运行时组件（DQ Monitor、Feature Store 等）必须实现透明降级到进程内存储（InMemoryStateStore 模式），确保 Redis 不可用时核心功能不中断。

**实现模式**:
1. `_state_get(key)` / `_state_set(key, value)` 封装所有 Redis 操作
2. Redis 异常时调用 `_enter_degraded_mode(reason)` 切换标志（仅日志一次）
3. `is_degraded` 属性暴露当前状态供监控查询
4. 降级后状态为进程本地，不保证跨进程一致性（已知限制，需文档声明）

**约束**:
- 降级切换 MUST 为单向（不自动恢复，避免 flapping）
- 降级事件 MUST 记录 WARNING 日志（仅一次）
- 配置 `use_in_memory_fallback=True`（默认）启用；`=False` 时 Redis 失败返回 None

落地：`quantflow/data/dq_monitor.py` InMemoryStateStore + _state_get/_state_set。测试：`tests/unit/test_dq_monitor_fallback.py` 14 测试。
</spec-entry>

<spec-entry category="arch" keywords="alert,deduplication,sliding-window,routing-matrix,alert-fatigue,notification" date="2026-08-02" sid="S-20260802-alert-dedup" title="告警路由矩阵 + 滑动窗口去重必须成对使用" description="AlertManager.send_routed() 必须同时应用 ALERT_ROUTING 路由和 AlertDeduplicator 去重，防止告警疲劳" source="harvest:ralph-v2-20260802-220000">

### 告警路由矩阵 + 滑动窗口去重必须成对使用

**规则**: 所有生产告警 MUST 通过 `AlertManager.send_routed()` 发送（而非原始 `send()`），确保：
1. ALERT_ROUTING 矩阵决定目标通道（category × priority → channels）
2. AlertDeduplicator 滑动窗口去重（默认 5 分钟）防止重复轰炸

**ALERT_ROUTING 结构**: `dict[tuple[AlertCategory, AlertPriority], list[str]]`
- P0_EMERGENCY → ["telegram", "webhook"]（全通道即时）
- P1_HIGH → ["telegram"]（5 分钟内通知）
- P2_MEDIUM → ["telegram"]（30 分钟内）
- P3_LOW → ["webhook"]（批量/下一工作日）
- 未映射组合 → DEFAULT_ALERT_CHANNELS ["telegram"]

**去重约束**:
- 去重键 = `f"{category.value}:{symbol}"`
- 窗口内重复 → 返回空 dict（抑制），不发送
- `suppressed_count` 属性供监控查询抑制数量

落地：`quantflow/monitoring/alerts.py` ALERT_ROUTING + AlertDeduplicator + send_routed()。测试：`tests/unit/test_alert_routing.py` 18 测试。
</spec-entry>

<spec-entry category="arch" keywords="positioning,mid-low-frequency,no-rust-rewrite,execution-performance,scenario-selection" date="2026-08-03" sid="S-BM2603-RD0" title="QuantFlow 接受中低频定位，不追赶 Rust/C++ 执行核心" description="演进路线图 RD-0 决策：执行性能代差为数量级且追赶收益限于订单簿高频/做市场景，接受中低频定位不重写，资源投向多源数据与 AI 管道" source="harvest:maestro-benchmark-evolve-20260803-20260803-045922">

### QuantFlow 接受中低频定位，不追赶 Rust/C++ 执行核心

**决策（roadmap RD-0, accepted）**: 接受个人/小团队中低频 Crypto（OKX）定位，**不追赶** Rust/C++ 执行核心重写。

**理由**:
1. 纯 Python vs Rust/C++ 核心为数量级性能差距（对标 NautilusTrader Rust 核心纳秒级/百万事件每秒），追赶是全路线图最高成本项。
2. 性能差距实际影响限于订单簿高频/做市场景——不在 QuantFlow 目标场景内，不阻断中低频。
3. 现有事件驱动 + 异步架构（TradingSession、gateway 有界重连、WS 退避）+ 场景选择足以规避该代差。
4. 同等资源投向可追赶且决定 Alpha 的维度：多源数据（最大结构性短板）与 AI 研究管道（最高性价比入口），边际收益远高于性能追赶。

**接受的代价（显式记录）**:
- 永久放弃订单簿微观结构高频/做市场景。
- 订单簿数据仅可以低频快照形式用于特征（非 tick 级建模）。

**不变量（配套）**: 尊重六层架构不做破坏性重构；新增防线（对账/熔断/恢复）一律 fail-closed；保持 TradingSession 单一真理源，仅收敛 parity 细节不推翻架构。

**信息边界**: 外部平台性能数字（NautilusTrader 百万级事件/秒等）为用户调研材料二手转述，未独立核验；即便性能差距小于转述，追赶性价比仍低于数据/AI 投入，故方向性结论不依赖外部数字精确性。

来源：session maestro-benchmark-evolve-20260803-20260803-045922 run 20260803-002-roadmap（roadmap.json positioning_decision / report RD-0）。
</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-03" sid="S-20260803-665be00842577168" title="审查方式：三维审查代理（正确性 Ryan/回归影响 Daniel）仅返回 diff 转储无结论文本，完整性维度连续 3 次派发失败（Mark 空输出、Kim/Ray 上下文取消、Tina 仅转储报告）→ 改由 supervisor 以清单核" description="Promoted from run:20260803-004-review, artifact:ART-004-001, artifact:ART-004-002, artifact:ART-004-003" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-665be00842577168">

### 审查方式：三维审查代理（正确性 Ryan/回归影响 Daniel）仅返回 diff 转储无结论文本，完整性维度连续 3 次派发失败（Mark 空输出、Kim/Ray 上下文取消、Tina 仅转储报告）→ 改由 supervisor 以清单核

审查方式：三维审查代理（正确性 Ryan/回归影响 Daniel）仅返回 diff 转储无结论文本，完整性维度连续 3 次派发失败（Mark 空输出、Kim/Ray 上下文取消、Tina 仅转储报告）→ 改由 supervisor 以清单核对 + 代码抽查方式完成三维审查，结论基于提交 a3c7bdd 实际变更与测试证据

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-03" sid="S-20260803-0057e42d4d93880e" title="T-s2-04 meta feed 以截止时间制调度（next_funding_at/next_oi_at），采集异常仅日志不中断；EVENT_FUNDING/EVENT_OI 定义在 strategy/engine.py 本地（不改 co" description="Promoted from run:20260803-003-execute, artifact:ART-003-001, artifact:ART-003-002" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-0057e42d4d93880e">

### T-s2-04 meta feed 以截止时间制调度（next_funding_at/next_oi_at），采集异常仅日志不中断；EVENT_FUNDING/EVENT_OI 定义在 strategy/engine.py 本地（不改 co

T-s2-04 meta feed 以截止时间制调度（next_funding_at/next_oi_at），采集异常仅日志不中断；EVENT_FUNDING/EVENT_OI 定义在 strategy/engine.py 本地（不改 common/event_bus.py）

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-03" sid="S-20260803-0d1c433b69fe755e" title="X3（ExchangeHealthMonitor 生产组装缺失）维持 execute 报告定级 medium 不阻塞本次 PASS：当前行为=默认关闭零变化，回退路径完整；作为 wave1 收尾遗留项登记，由后续集成任务补齐并做 kill " description="Promoted from run:20260803-004-review, artifact:ART-004-001, artifact:ART-004-002, artifact:ART-004-003" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-0d1c433b69fe755e">

### X3（ExchangeHealthMonitor 生产组装缺失）维持 execute 报告定级 medium 不阻塞本次 PASS：当前行为=默认关闭零变化，回退路径完整；作为 wave1 收尾遗留项登记，由后续集成任务补齐并做 kill 

X3（ExchangeHealthMonitor 生产组装缺失）维持 execute 报告定级 medium 不阻塞本次 PASS：当前行为=默认关闭零变化，回退路径完整；作为 wave1 收尾遗留项登记，由后续集成任务补齐并做 kill switch 端到端演练

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-03" sid="S-20260803-203718bb460c54f3" title="fail-closed 语义抽查通过：熔断开启全拒（含 FLAT）、恢复未验证拒新单放行 FLAT、funding/OI 过期只拦 entry 放行 exit、corrupt checkpoint 拒恢复" description="Promoted from run:20260803-004-review, artifact:ART-004-001, artifact:ART-004-002, artifact:ART-004-003" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-203718bb460c54f3">

### fail-closed 语义抽查通过：熔断开启全拒（含 FLAT）、恢复未验证拒新单放行 FLAT、funding/OI 过期只拦 entry 放行 exit、corrupt checkpoint 拒恢复

fail-closed 语义抽查通过：熔断开启全拒（含 FLAT）、恢复未验证拒新单放行 FLAT、funding/OI 过期只拦 entry 放行 exit、corrupt checkpoint 拒恢复

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-03" sid="S-20260803-4e7d96a73533ce47" title="六层架构单向依赖无违规：exchange_health 在 L5 只依赖 common/（MonitoringSink Protocol/EventBus）；RiskEngine 以 duck-type 注入接收 monitor；dq_mo" description="Promoted from run:20260803-004-review, artifact:ART-004-001, artifact:ART-004-002, artifact:ART-004-003" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-4e7d96a73533ce47">

### 六层架构单向依赖无违规：exchange_health 在 L5 只依赖 common/（MonitoringSink Protocol/EventBus）；RiskEngine 以 duck-type 注入接收 monitor；dq_mo

六层架构单向依赖无违规：exchange_health 在 L5 只依赖 common/（MonitoringSink Protocol/EventBus）；RiskEngine 以 duck-type 注入接收 monitor；dq_monitor/strategy 走 monitoring_sink Protocol

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-03" sid="S-20260803-7f2d4046179eb872" title="T-s1-04 熔断拦截点放 RiskEngine.check 的 _checks 元组最前（信号单一入口），kill switch 联动复用 EVENT_RISK severity=emergency 既有路径（monitor 触发时 p" description="Promoted from run:20260803-003-execute, artifact:ART-003-001, artifact:ART-003-002" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-7f2d4046179eb872">

### T-s1-04 熔断拦截点放 RiskEngine.check 的 _checks 元组最前（信号单一入口），kill switch 联动复用 EVENT_RISK severity=emergency 既有路径（monitor 触发时 p

T-s1-04 熔断拦截点放 RiskEngine.check 的 _checks 元组最前（信号单一入口），kill switch 联动复用 EVENT_RISK severity=emergency 既有路径（monitor 触发时 publish）

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-03" sid="S-20260803-8198c2cd469921f2" title="byte-for-byte backtest baseline：generate_signals 语义零变化（base.py 仅 docstring）；parity 测试 paper_entries ⊆ backtest_entries 超" description="Promoted from run:20260803-004-review, artifact:ART-004-001, artifact:ART-004-002, artifact:ART-004-003" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-8198c2cd469921f2">

### byte-for-byte backtest baseline：generate_signals 语义零变化（base.py 仅 docstring）；parity 测试 paper_entries ⊆ backtest_entries 超

byte-for-byte backtest baseline：generate_signals 语义零变化（base.py 仅 docstring）；parity 测试 paper_entries ⊆ backtest_entries 超集断言 3 通过

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-03" sid="S-20260803-97caee9923769e31" title="T-s2-04 新鲜度 gate 双实现同源：TradingSession._meta_data_fresh 与 dq_monitor validator 共用 market_meta_fetcher 常量（FUNDING_MAX_AGE_" description="Promoted from run:20260803-003-execute, artifact:ART-003-001, artifact:ART-003-002" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-97caee9923769e31">

### T-s2-04 新鲜度 gate 双实现同源：TradingSession._meta_data_fresh 与 dq_monitor validator 共用 market_meta_fetcher 常量（FUNDING_MAX_AGE_

T-s2-04 新鲜度 gate 双实现同源：TradingSession._meta_data_fresh 与 dq_monitor validator 共用 market_meta_fetcher 常量（FUNDING_MAX_AGE_FACTOR=2×结算周期运行时判定、OI_MAX_AGE_S=600）

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-03" sid="S-20260803-b0f01838ff52ee67" title="funding 历史回填按 OKX 已核验 3 个月窗口截断（roadmap 180 天字面要求不可达），OI 180 天经 period=1H 分页可达" description="Promoted from run:20260803-002-plan, artifact:ART-002-001, artifact:ART-002-003" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-b0f01838ff52ee67">

### funding 历史回填按 OKX 已核验 3 个月窗口截断（roadmap 180 天字面要求不可达），OI 180 天经 period=1H 分页可达

funding 历史回填按 OKX 已核验 3 个月窗口截断（roadmap 180 天字面要求不可达），OI 180 天经 period=1H 分页可达

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-03" sid="S-20260803-d3702539fcfc1f69" title="T-s1-05 regime gate 分歧按核验降级为可测试断言 paper_entries ⊆ backtest_entries（不把 regime 过滤引入 generate_signals，保护 backtest 基线）；paper" description="Promoted from run:20260803-003-execute, artifact:ART-003-001, artifact:ART-003-002" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-d3702539fcfc1f69">

### T-s1-05 regime gate 分歧按核验降级为可测试断言 paper_entries ⊆ backtest_entries（不把 regime 过滤引入 generate_signals，保护 backtest 基线）；paper

T-s1-05 regime gate 分歧按核验降级为可测试断言 paper_entries ⊆ backtest_entries（不把 regime 过滤引入 generate_signals，保护 backtest 基线）；paper 重放走真实 TradingSession 而非引擎复刻

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-03" sid="S-20260803-d9b47940cad9e286" title="所有新行为默认关闭（exchange_health.enabled=false / state.enabled=false / reconciliation.enabled=false / funding_feed_enabled=fals" description="Promoted from run:20260803-004-review, artifact:ART-004-001, artifact:ART-004-002, artifact:ART-004-003" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-d9b47940cad9e286">

### 所有新行为默认关闭（exchange_health.enabled=false / state.enabled=false / reconciliation.enabled=false / funding_feed_enabled=fals

所有新行为默认关闭（exchange_health.enabled=false / state.enabled=false / reconciliation.enabled=false / funding_feed_enabled=false / exchange_exposure_limit_pct=None 默认），回退=改配置

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-03" sid="S-20260803-e7acc7e6a03b34ea" title="s2 采集器自限频：funding 轮询 ≥60s、OI ≥30s、RateLimiter 单端点 ≥200ms、50011/网络错误指数退避 3 次；OI 只走 REST" description="Promoted from run:20260803-003-execute, artifact:ART-003-001, artifact:ART-003-002" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-e7acc7e6a03b34ea">

### s2 采集器自限频：funding 轮询 ≥60s、OI ≥30s、RateLimiter 单端点 ≥200ms、50011/网络错误指数退避 3 次；OI 只走 REST

s2 采集器自限频：funding 轮询 ≥60s、OI ≥30s、RateLimiter 单端点 ≥200ms、50011/网络错误指数退避 3 次；OI 只走 REST

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-03" sid="S-20260803-134ac997f0b29090" title="核验步骤只读，不改项目源码；本轮不实施 s2" description="Promoted from run:20260803-001-analyze, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-134ac997f0b29090">

### 核验步骤只读，不改项目源码；本轮不实施 s2

核验步骤只读，不改项目源码；本轮不实施 s2

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-03" sid="S-20260803-23823e0b270277af" title="公共 REST 限频按 IP + Instrument ID 计，超限返回 50011（HTTP 200/429）" description="Promoted from run:20260803-001-analyze, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-23823e0b270277af">

### 公共 REST 限频按 IP + Instrument ID 计，超限返回 50011（HTTP 200/429）

公共 REST 限频按 IP + Instrument ID 计，超限返回 50011（HTTP 200/429）

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-03" sid="S-20260803-346ec75d383fcf49" title="任务粒度：9 任务（s1×5 + s2×4），3 wave（4+2+3），每 wave 内写文件零交集；critical path = T-s2-01→T-s2-03→T-s2-04" description="Promoted from run:20260803-002-plan, artifact:ART-002-001, artifact:ART-002-003" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-346ec75d383fcf49">

### 任务粒度：9 任务（s1×5 + s2×4），3 wave（4+2+3），每 wave 内写文件零交集；critical path = T-s2-01→T-s2-03→T-s2-04

任务粒度：9 任务（s1×5 + s2×4），3 wave（4+2+3），每 wave 内写文件零交集；critical path = T-s2-01→T-s2-03→T-s2-04

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-03" sid="S-20260803-547c27618bfb4e29" title="default.yaml 按 wave 分配写权（w1=T-s1-01, w2=T-s1-03, w3=T-s1-04）；T-s2-04 的 funding_feed_enabled 置于 funding_rate.yaml 规避 w3 冲" description="Promoted from run:20260803-002-plan, artifact:ART-002-001, artifact:ART-002-003" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-547c27618bfb4e29">

### default.yaml 按 wave 分配写权（w1=T-s1-01, w2=T-s1-03, w3=T-s1-04）；T-s2-04 的 funding_feed_enabled 置于 funding_rate.yaml 规避 w3 冲

default.yaml 按 wave 分配写权（w1=T-s1-01, w2=T-s1-03, w3=T-s1-04）；T-s2-04 的 funding_feed_enabled 置于 funding_rate.yaml 规避 w3 冲突

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-03" sid="S-20260803-5de35c18bea3a7f2" title="T-s1-04 敞口 gate 仅拦 Direction.LONG 新开仓，FLAT/退出放行以便降敞（fail-closed 不能变 fail-stuck）；exposure = Σ|qty|×price + pending 正值和" description="Promoted from run:20260803-003-execute, artifact:ART-003-001, artifact:ART-003-002" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-5de35c18bea3a7f2">

### T-s1-04 敞口 gate 仅拦 Direction.LONG 新开仓，FLAT/退出放行以便降敞（fail-closed 不能变 fail-stuck）；exposure = Σ|qty|×price + pending 正值和

T-s1-04 敞口 gate 仅拦 Direction.LONG 新开仓，FLAT/退出放行以便降敞（fail-closed 不能变 fail-stuck）；exposure = Σ|qty|×price + pending 正值和

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-03" sid="S-20260803-807c564e121dad83" title="T-s1-02 write 清单含 tests/unit/test_order_manager.py 但提交未改该文件（ws 接线测试落在 test_execution_engine.py）— 轻微偏差，验收口径不受影响（8 态路径已由执行" description="Promoted from run:20260803-004-review, artifact:ART-004-001, artifact:ART-004-002, artifact:ART-004-003" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-807c564e121dad83">

### T-s1-02 write 清单含 tests/unit/test_order_manager.py 但提交未改该文件（ws 接线测试落在 test_execution_engine.py）— 轻微偏差，验收口径不受影响（8 态路径已由执行

T-s1-02 write 清单含 tests/unit/test_order_manager.py 但提交未改该文件（ws 接线测试落在 test_execution_engine.py）— 轻微偏差，验收口径不受影响（8 态路径已由执行报告测试覆盖），登记为流程偏差不追责

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-03" sid="S-20260803-a19f4a62f2a03b9d" title="资金费率结算周期通常 8h，但 OKX 可对个别币种调整为 6/4/2/1h，必须以 fundingTime/nextFundingTime 差值为准" description="Promoted from run:20260803-001-analyze, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-a19f4a62f2a03b9d">

### 资金费率结算周期通常 8h，但 OKX 可对个别币种调整为 6/4/2/1h，必须以 fundingTime/nextFundingTime 差值为准

资金费率结算周期通常 8h，但 OKX 可对个别币种调整为 6/4/2/1h，必须以 fundingTime/nextFundingTime 差值为准

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-03" sid="S-20260803-a7ecff81ad00735f" title="不越界 s3/s4，不改 frontend；API Key 只走环境变量" description="Promoted from run:20260803-002-plan, artifact:ART-002-001, artifact:ART-002-003" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-a7ecff81ad00735f">

### 不越界 s3/s4，不改 frontend；API Key 只走环境变量

不越界 s3/s4，不改 frontend；API Key 只走环境变量

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-03" sid="S-20260803-c32d2aa259bb210d" title="采集能力落新模块 quantflow/data/market_meta_fetcher.py（共享 ccxt 实例注入接口），fetcher.py 全 wave 只读，避免 OHLCV 主路径互扰" description="Promoted from run:20260803-002-plan, artifact:ART-002-001, artifact:ART-002-003" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-c32d2aa259bb210d">

### 采集能力落新模块 quantflow/data/market_meta_fetcher.py（共享 ccxt 实例注入接口），fetcher.py 全 wave 只读，避免 OHLCV 主路径互扰

采集能力落新模块 quantflow/data/market_meta_fetcher.py（共享 ccxt 实例注入接口），fetcher.py 全 wave 只读，避免 OHLCV 主路径互扰

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-03" sid="S-20260803-278bb5b69ff9e27d" title="六层架构单向依赖：reconciliation/risk_engine 对 L4/L5 一律 duck-type/Protocol 注入，不新增跨层 import" description="Promoted from run:20260803-002-plan, artifact:ART-002-001, artifact:ART-002-003" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-278bb5b69ff9e27d">

### 六层架构单向依赖：reconciliation/risk_engine 对 L4/L5 一律 duck-type/Protocol 注入，不新增跨层 import

六层架构单向依赖：reconciliation/risk_engine 对 L4/L5 一律 duck-type/Protocol 注入，不新增跨层 import

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-03" sid="S-20260803-3c582f3d4af02b8d" title="byte-for-byte backtest baseline：generate_signals 语义零变化（T-s1-05 parity 回归 + 既有基线全绿证明）；strategy/engine.py 按 w2→w3 串行写" description="Promoted from run:20260803-003-execute, artifact:ART-003-001, artifact:ART-003-002" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-3c582f3d4af02b8d">

### byte-for-byte backtest baseline：generate_signals 语义零变化（T-s1-05 parity 回归 + 既有基线全绿证明）；strategy/engine.py 按 w2→w3 串行写

byte-for-byte backtest baseline：generate_signals 语义零变化（T-s1-05 parity 回归 + 既有基线全绿证明）；strategy/engine.py 按 w2→w3 串行写

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-03" sid="S-20260803-4318900fbe468be3" title="byte-for-byte backtest baseline：generate_signals 默认语义不变；strategy/engine.py 双写者 wave 串行（w2→w3）" description="Promoted from run:20260803-002-plan, artifact:ART-002-001, artifact:ART-002-003" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-4318900fbe468be3">

### byte-for-byte backtest baseline：generate_signals 默认语义不变；strategy/engine.py 双写者 wave 串行（w2→w3）

byte-for-byte backtest baseline：generate_signals 默认语义不变；strategy/engine.py 双写者 wave 串行（w2→w3）

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-03" sid="S-20260803-44d14b841c80fa2f" title="YAML 配置驱动且所有新行为默认关闭（state.enabled/reconciliation.enabled/funding_feed_enabled/exchange_health.enabled 均默认 false），回退=改配置" description="Promoted from run:20260803-002-plan, artifact:ART-002-001, artifact:ART-002-003" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-44d14b841c80fa2f">

### YAML 配置驱动且所有新行为默认关闭（state.enabled/reconciliation.enabled/funding_feed_enabled/exchange_health.enabled 均默认 false），回退=改配置

YAML 配置驱动且所有新行为默认关闭（state.enabled/reconciliation.enabled/funding_feed_enabled/exchange_health.enabled 均默认 false），回退=改配置

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-03" sid="S-20260803-6200a89a62431482" title="s2 采集器自限频（≥200ms 单端点间隔 + IP 级串行），不依赖 ccxt 内置节流；OI 只走 REST 轮询（无 watchOpenInterest）" description="Promoted from run:20260803-002-plan, artifact:ART-002-001, artifact:ART-002-003" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-6200a89a62431482">

### s2 采集器自限频（≥200ms 单端点间隔 + IP 级串行），不依赖 ccxt 内置节流；OI 只走 REST 轮询（无 watchOpenInterest）

s2 采集器自限频（≥200ms 单端点间隔 + IP 级串行），不依赖 ccxt 内置节流；OI 只走 REST 轮询（无 watchOpenInterest）

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-03" sid="S-20260803-73ea6ff39c99071a" title="default.yaml 写权按 wave 分配（w1=T-s1-01、w2=T-s1-03、w3=T-s1-04）；T-s2-04 的 funding_feed_enabled 落 funding_rate.yaml；fetcher.py" description="Promoted from run:20260803-003-execute, artifact:ART-003-001, artifact:ART-003-002" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-73ea6ff39c99071a">

### default.yaml 写权按 wave 分配（w1=T-s1-01、w2=T-s1-03、w3=T-s1-04）；T-s2-04 的 funding_feed_enabled 落 funding_rate.yaml；fetcher.py

default.yaml 写权按 wave 分配（w1=T-s1-01、w2=T-s1-03、w3=T-s1-04）；T-s2-04 的 funding_feed_enabled 落 funding_rate.yaml；fetcher.py 全 wave 只读

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-03" sid="S-20260803-85cb098b6fd32559" title="熔断拦截点选 RiskEngine.check（信号单一入口）而非 ExecutionEngine.submit；kill switch 联动复用 EVENT_RISK emergency 既有路径" description="Promoted from run:20260803-002-plan, artifact:ART-002-001, artifact:ART-002-003" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-85cb098b6fd32559">

### 熔断拦截点选 RiskEngine.check（信号单一入口）而非 ExecutionEngine.submit；kill switch 联动复用 EVENT_RISK emergency 既有路径

熔断拦截点选 RiskEngine.check（信号单一入口）而非 ExecutionEngine.submit；kill switch 联动复用 EVENT_RISK emergency 既有路径

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-03" sid="S-20260803-8b9b705c3c8f0f9a" title="六层架构单向依赖：RiskEngine 对 exchange_health 用 object duck-type（只依赖 circuit_open() 形状），dq_monitor/strategy 对 L6 用 common/monito" description="Promoted from run:20260803-003-execute, artifact:ART-003-001, artifact:ART-003-002" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-8b9b705c3c8f0f9a">

### 六层架构单向依赖：RiskEngine 对 exchange_health 用 object duck-type（只依赖 circuit_open() 形状），dq_monitor/strategy 对 L6 用 common/monito

六层架构单向依赖：RiskEngine 对 exchange_health 用 object duck-type（只依赖 circuit_open() 形状），dq_monitor/strategy 对 L6 用 common/monitoring_sink Protocol，无新增跨层 import

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-03" sid="S-20260803-95335dff0c90b74c" title="fail-closed：熔断开启全拒（含 FLAT）、恢复未验证拒新单、funding/OI 过期只拦新开仓不拦退出、feed 无数据视为过期" description="Promoted from run:20260803-003-execute, artifact:ART-003-001, artifact:ART-003-002" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-95335dff0c90b74c">

### fail-closed：熔断开启全拒（含 FLAT）、恢复未验证拒新单、funding/OI 过期只拦新开仓不拦退出、feed 无数据视为过期

fail-closed：熔断开启全拒（含 FLAT）、恢复未验证拒新单、funding/OI 过期只拦新开仓不拦退出、feed 无数据视为过期

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-03" sid="S-20260803-a7ab06d97fac0da2" title="YAML 配置驱动且所有新行为默认关闭（exchange_health.enabled=false、funding_feed_enabled=false、exchange_exposure_limit_pct pydantic 默认 Non" description="Promoted from run:20260803-003-execute, artifact:ART-003-001, artifact:ART-003-002" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-a7ab06d97fac0da2">

### YAML 配置驱动且所有新行为默认关闭（exchange_health.enabled=false、funding_feed_enabled=false、exchange_exposure_limit_pct pydantic 默认 Non

YAML 配置驱动且所有新行为默认关闭（exchange_health.enabled=false、funding_feed_enabled=false、exchange_exposure_limit_pct pydantic 默认 None），回退=改配置

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-03" sid="S-20260803-b0360407cccb1371" title="funding-rate-history 仅覆盖近 3 个月；OI history 数据最早到 2024 年初且单端点最多 1440 条" description="Promoted from run:20260803-001-analyze, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-b0360407cccb1371">

### funding-rate-history 仅覆盖近 3 个月；OI history 数据最早到 2024 年初且单端点最多 1440 条

funding-rate-history 仅覆盖近 3 个月；OI history 数据最早到 2024 年初且单端点最多 1440 条

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-03" sid="S-20260803-ed55f2ed3be32d6d" title="R1: 审查代理连续失效后改 supervisor 清单核对+代码抽查模式完成三维审查" description="Promoted from run:20260803-004-review, artifact:ART-004-001, artifact:ART-004-002, artifact:ART-004-003" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-ed55f2ed3be32d6d">

### R1: 审查代理连续失效后改 supervisor 清单核对+代码抽查模式完成三维审查

R1: 审查代理连续失效后改 supervisor 清单核对+代码抽查模式完成三维审查

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-03" sid="S-20260803-f7dd4c2353e6ee9b" title="fail-closed：对账失败保留 last-known、恢复未验证拒新单、数据过期暂停新开仓、熔断全拒+滞回恢复" description="Promoted from run:20260803-002-plan, artifact:ART-002-001, artifact:ART-002-003" source="session:maestro-wave1-precheck-20260803-20260803-075540:KDC-f7dd4c2353e6ee9b">

### fail-closed：对账失败保留 last-known、恢复未验证拒新单、数据过期暂停新开仓、熔断全拒+滞回恢复

fail-closed：对账失败保留 last-known、恢复未验证拒新单、数据过期暂停新开仓、熔断全拒+滞回恢复

</spec-entry>

<spec-entry category="arch" keywords="ai,module,layer,import" date="2026-08-04" sid="S-20260804-w2s3-ai" title="AI 模块层间引用约束：L1-only 导入 + 零 L2/L3 引用" description="AI 模块严格遵循层间引用约束：feature_store.py 仅导入 common/ + data/（L1 内部），零 L2/L3 引用；meta_features.py 零 quantflow 导入（纯 pandas L2 计算器）；ai_training.py 唯一 quantflow 导入 = validation.gate（L3 同级，函数局部）。" source="harvest:maestro-wave2-s3-20260803-20260804-040400">

### AI 模块层间引用约束：L1-only 导入 + 零 L2/L3 引用

AI 模块严格遵循层间引用约束：
- feature_store.py 仅导入 common/ + data/（L1 内部），零 L2/L3 引用
- meta_features.py 零 quantflow 导入（纯 pandas L2 计算器）
- ai_training.py 唯一 quantflow 导入 = validation.gate（L3 同级，函数局部）
- 所有新模块默认关闭（ai.rdagent.enabled=false / model_registry_enabled=false）

</spec-entry>

<spec-entry category="arch" keywords="ai,model,allowlist,security" date="2026-08-04" sid="S-20260804-w3s4-ai-allowlist" title="AIFactorStrategy 模型实例化白名单安全设计：仅允许 RF/LogReg/GBM" description="AIFactorStrategy 模型实例化使用白名单仅允许 RF/LogReg/GBM，禁止 eval 执行，未知类 → None + warning。P(up) gates momentum 阈值（>=entry threshold 做多 / <=exit threshold 退出）。" source="harvest:maestro-wave3-s4-20260804-20260804-054608">

### AIFactorStrategy 模型实例化白名单安全设计

- 白名单：仅允许 RF/LogReg/GBM，禁止 eval 执行
- 未知类 → 返回 None + warning
- P(up) gates momentum 阈值做多/退出
- 能力退化：空 registry / corrupt JSON / 未知 id / predict 失败 → momentum 降级，永不 raise

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-05" sid="S-20260805-135d47ea99bb1e07" title="新文件（market_meta_fetcher/exchange_health/state_store）仅报告不自动加入 code_locations" description="Promoted from run:20260805-001-codebase-refresh, artifact:ART-001-001, artifact:ART-001-002" source="session:20260805-maestro-knowledge-sync-20260805-052529:KDC-135d47ea99bb1e07">

### 新文件（market_meta_fetcher/exchange_health/state_store）仅报告不自动加入 code_locations

新文件（market_meta_fetcher/exchange_health/state_store）仅报告不自动加入 code_locations

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-05" sid="S-20260805-199fcb4c946d1f68" title="AST 全组件扫描（不只变更文件）以获得准确组件级符号 diff；仅收录公开符号（类/公开函数/全大写常量），_ 私有符号不入 symbols[]" description="Promoted from run:20260805-001-codebase-refresh, artifact:ART-001-001, artifact:ART-001-002" source="session:20260805-maestro-knowledge-sync-20260805-052529:KDC-199fcb4c946d1f68">

### AST 全组件扫描（不只变更文件）以获得准确组件级符号 diff；仅收录公开符号（类/公开函数/全大写常量），_ 私有符号不入 symbols[]

AST 全组件扫描（不只变更文件）以获得准确组件级符号 diff；仅收录公开符号（类/公开函数/全大写常量），_ 私有符号不入 symbols[]

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-05" sid="S-20260805-2d44af414372d808" title="TC-004 注册 quantflow/signal/optimizer.py（已存在但未记录，TradingSession 依赖）" description="Promoted from run:20260805-001-codebase-refresh, artifact:ART-001-001, artifact:ART-001-002" source="session:20260805-maestro-knowledge-sync-20260805-052529:KDC-2d44af414372d808">

### TC-004 注册 quantflow/signal/optimizer.py（已存在但未记录，TradingSession 依赖）

TC-004 注册 quantflow/signal/optimizer.py（已存在但未记录，TradingSession 依赖）

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-05" sid="S-20260805-4519939fd1d503f8" title="仅写入 .workflow/knowhow/（wiki update frontmatter），未修改源码、未 commit" description="Promoted from run:20260805-003-wiki-manage, artifact:ART-003-001, artifact:ART-003-002, artifact:ART-003-003" source="session:20260805-maestro-knowledge-sync-20260805-052529:KDC-4519939fd1d503f8">

### 仅写入 .workflow/knowhow/（wiki update frontmatter），未修改源码、未 commit

仅写入 .workflow/knowhow/（wiki update frontmatter），未修改源码、未 commit

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-05" sid="S-20260805-49225c5b3b0a2724" title="3 个 sourceRef=20260802-team-ui-polish-continuous 的 knowhow 链接到 session-20260802-team-ui-polish-full：continuous 为 running" description="Promoted from run:20260805-003-wiki-manage, artifact:ART-003-001, artifact:ART-003-002, artifact:ART-003-003" source="session:20260805-maestro-knowledge-sync-20260805-052529:KDC-49225c5b3b0a2724">

### 3 个 sourceRef=20260802-team-ui-polish-continuous 的 knowhow 链接到 session-20260802-team-ui-polish-full：continuous 为 running

3 个 sourceRef=20260802-team-ui-polish-continuous 的 knowhow 链接到 session-20260802-team-ui-polish-full：continuous 为 running session（未入 wiki 索引，链接会变 broken），full 为同系列已入索引 session，语义等价

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-05" sid="S-20260805-642e67983de99b4c" title="为 FT-011/FT-012 创建缺失的 feature-map（组件已刷新、文档缺失），_index.md 全量重建补齐 TC-013/FT-011/012/013 行" description="Promoted from run:20260805-001-codebase-refresh, artifact:ART-001-001, artifact:ART-001-002" source="session:20260805-maestro-knowledge-sync-20260805-052529:KDC-642e67983de99b4c">

### 为 FT-011/FT-012 创建缺失的 feature-map（组件已刷新、文档缺失），_index.md 全量重建补齐 TC-013/FT-011/012/013 行

为 FT-011/FT-012 创建缺失的 feature-map（组件已刷新、文档缺失），_index.md 全量重建补齐 TC-013/FT-011/012/013 行

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-05" sid="S-20260805-92ec22de14bd264e" title="仅修改 .workflow/codebase/ 与 .workflow/state.json，未触碰源码（git status 源码变更均为先前存在的未提交工作区状态）" description="Promoted from run:20260805-001-codebase-refresh, artifact:ART-001-001, artifact:ART-001-002" source="session:20260805-maestro-knowledge-sync-20260805-052529:KDC-92ec22de14bd264e">

### 仅修改 .workflow/codebase/ 与 .workflow/state.json，未触碰源码（git status 源码变更均为先前存在的未提交工作区状态）

仅修改 .workflow/codebase/ 与 .workflow/state.json，未触碰源码（git status 源码变更均为先前存在的未提交工作区状态）

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-05" sid="S-20260805-9451480316a389fd" title="Step 3.6 KG 分析因 CLI 命令缺失降级为基于 knowledge-graph.json 的推理（[LOW CONFIDENCE]）" description="Promoted from run:20260805-001-codebase-refresh, artifact:ART-001-001, artifact:ART-001-002" source="session:20260805-maestro-knowledge-sync-20260805-052529:KDC-9451480316a389fd">

### Step 3.6 KG 分析因 CLI 命令缺失降级为基于 knowledge-graph.json 的推理（[LOW CONFIDENCE]）

Step 3.6 KG 分析因 CLI 命令缺失降级为基于 knowledge-graph.json 的推理（[LOW CONFIDENCE]）

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-05" sid="S-20260805-9c1f3702f0da5f33" title="4 个 kh/TIP 条目经 BM25 语义验证后链接到 spec 子条目（arch-020/cc-016/cc-017/learnings-012），与 source 语义一一对应" description="Promoted from run:20260805-003-wiki-manage, artifact:ART-003-001, artifact:ART-003-002, artifact:ART-003-003" source="session:20260805-maestro-knowledge-sync-20260805-052529:KDC-9c1f3702f0da5f33">

### 4 个 kh/TIP 条目经 BM25 语义验证后链接到 spec 子条目（arch-020/cc-016/cc-017/learnings-012），与 source 语义一一对应

4 个 kh/TIP 条目经 BM25 语义验证后链接到 spec 子条目（arch-020/cc-016/cc-017/learnings-012），与 source 语义一一对应

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-05" sid="S-20260805-cec2635fa99302a5" title="19 broken links 与 project-project missing title 均超出写边界（sealed sessions/ 与 .workflow/project.md），仅记录不修复" description="Promoted from run:20260805-003-wiki-manage, artifact:ART-003-001, artifact:ART-003-002, artifact:ART-003-003" source="session:20260805-maestro-knowledge-sync-20260805-052529:KDC-cec2635fa99302a5">

### 19 broken links 与 project-project missing title 均超出写边界（sealed sessions/ 与 .workflow/project.md），仅记录不修复

19 broken links 与 project-project missing title 均超出写边界（sealed sessions/ 与 .workflow/project.md），仅记录不修复

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-05" sid="S-20260805-d5329264bb31753e" title="kh-multi-symbol-patterns 无语义匹配目标（arch-019 不匹配、roadmap 无 multi-symbol 内容），跳过链接避免弱语义边" description="Promoted from run:20260805-003-wiki-manage, artifact:ART-003-001, artifact:ART-003-002, artifact:ART-003-003" source="session:20260805-maestro-knowledge-sync-20260805-052529:KDC-d5329264bb31753e">

### kh-multi-symbol-patterns 无语义匹配目标（arch-019 不匹配、roadmap 无 multi-symbol 内容），跳过链接避免弱语义边

kh-multi-symbol-patterns 无语义匹配目标（arch-019 不匹配、roadmap 无 multi-symbol 内容），跳过链接避免弱语义边

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-05" sid="S-20260805-dbc4a1cbcae4520e" title="KG 同步必须覆盖新写入的 wiki/spec/knowhow：已执行 kg sync 全源同步，staleness 0.0%" description="Promoted from run:20260805-003-wiki-manage, artifact:ART-003-001, artifact:ART-003-002, artifact:ART-003-003" source="session:20260805-maestro-knowledge-sync-20260805-052529:KDC-dbc4a1cbcae4520e">

### KG 同步必须覆盖新写入的 wiki/spec/knowhow：已执行 kg sync 全源同步，staleness 0.0%

KG 同步必须覆盖新写入的 wiki/spec/knowhow：已执行 kg sync 全源同步，staleness 0.0%

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-05" sid="S-20260805-ddff395ff1a3fe6b" title="doc-index 修复：删除 TC-013 reconciliation 重复条目（保留 dashboards TC-013）、FT-013 component_ids TC-012→TC-013、features 数组脏字符串清理、pr" description="Promoted from run:20260805-001-codebase-refresh, artifact:ART-001-001, artifact:ART-001-002" source="session:20260805-maestro-knowledge-sync-20260805-052529:KDC-ddff395ff1a3fe6b">

### doc-index 修复：删除 TC-013 reconciliation 重复条目（保留 dashboards TC-013）、FT-013 component_ids TC-012→TC-013、features 数组脏字符串清理、pr

doc-index 修复：删除 TC-013 reconciliation 重复条目（保留 dashboards TC-013）、FT-013 component_ids TC-012→TC-013、features 数组脏字符串清理、project_version 0.3.0→0.4.0

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-05" sid="S-20260805-e3af3239aa24e3a9" title="未执行 git commit" description="Promoted from run:20260805-001-codebase-refresh, artifact:ART-001-001, artifact:ART-001-002" source="session:20260805-maestro-knowledge-sync-20260805-052529:KDC-e3af3239aa24e3a9">

### 未执行 git commit

未执行 git commit

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-06" sid="S-20260806-0de19815a2b79672" title="0 信号视为有效验证结论（fail-closed）：前提不成立 → NO-GO，原型保持 disabled" description="Promoted from run:20260806-001-implement, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004" source="session:20260806-iss-20260804-003-spot-perp:KDC-0de19815a2b79672">

### 0 信号视为有效验证结论（fail-closed）：前提不成立 → NO-GO，原型保持 disabled

0 信号视为有效验证结论（fail-closed）：前提不成立 → NO-GO，原型保持 disabled

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-06" sid="S-20260806-5185acbdaeb7ad75" title="Pair P&amp;L 模型：perp 腿 d + spot 镜面腿 + funding -d×f（仅结算 bar）+ 双边费用；整 bar 语义对齐 BacktestEngine" description="Promoted from run:20260806-001-implement, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004" source="session:20260806-iss-20260804-003-spot-perp:KDC-5185acbdaeb7ad75">

### Pair P&L 模型：perp 腿 d + spot 镜面腿 + funding -d×f（仅结算 bar）+ 双边费用；整 bar 语义对齐 BacktestEngine

Pair P&L 模型：perp 腿 d + spot 镜面腿 + funding -d×f（仅结算 bar）+ 双边费用；整 bar 语义对齐 BacktestEngine

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-06" sid="S-20260806-58ffc83fb14f7bce" title="P0 回归基线随数据窗口漂移，需 establish_p0_baseline.py 重建（已执行）" description="Promoted from run:20260806-001-implement, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004" source="session:20260806-iss-20260804-003-spot-perp:KDC-58ffc83fb14f7bce">

### P0 回归基线随数据窗口漂移，需 establish_p0_baseline.py 重建（已执行）

P0 回归基线随数据窗口漂移，需 establish_p0_baseline.py 重建（已执行）

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-06" sid="S-20260806-5941f3edd1586f3d" title="D3: 0 信号视为有效结论，NO-GO，原型保持 disabled" description="Promoted from run:20260806-001-implement, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004" source="session:20260806-iss-20260804-003-spot-perp:KDC-5941f3edd1586f3d">

### D3: 0 信号视为有效结论，NO-GO，原型保持 disabled

D3: 0 信号视为有效结论，NO-GO，原型保持 disabled

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-06" sid="S-20260806-79d7c42b79056096" title="D1: 验证窗口以 OKX 可获取的 90 天为准" description="Promoted from run:20260806-001-implement, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004" source="session:20260806-iss-20260804-003-spot-perp:KDC-79d7c42b79056096">

### D1: 验证窗口以 OKX 可获取的 90 天为准

D1: 验证窗口以 OKX 可获取的 90 天为准

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-06" sid="S-20260806-89697d25a85ca5df" title="OKX funding-rate-history 仅服务 ~90 天，单页上限 100（实测 51000 拒绝 &gt;100）" description="Promoted from run:20260806-001-implement, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004" source="session:20260806-iss-20260804-003-spot-perp:KDC-89697d25a85ca5df">

### OKX funding-rate-history 仅服务 ~90 天，单页上限 100（实测 51000 拒绝 >100）

OKX funding-rate-history 仅服务 ~90 天，单页上限 100（实测 51000 拒绝 >100）

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-06" sid="S-20260806-928a025676af4b36" title="OKX rubik OI-volume 端点必须 begin+end 成对（单传 → 50030）；1H 仅最近 ~30 天，1D ~180 天，after 分页被忽略" description="Promoted from run:20260806-001-implement, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004" source="session:20260806-iss-20260804-003-spot-perp:KDC-928a025676af4b36">

### OKX rubik OI-volume 端点必须 begin+end 成对（单传 → 50030）；1H 仅最近 ~30 天，1D ~180 天，after 分页被忽略

OKX rubik OI-volume 端点必须 begin+end 成对（单传 → 50030）；1H 仅最近 ~30 天，1D ~180 天，after 分页被忽略

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-06" sid="S-20260806-d5dcd8b9b1944fc6" title="验证窗口以 OKX 可获取的 90 天为准；OI 30 天 cap 以 coverage 记录而非拼接虚构数据" description="Promoted from run:20260806-001-implement, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004" source="session:20260806-iss-20260804-003-spot-perp:KDC-d5dcd8b9b1944fc6">

### 验证窗口以 OKX 可获取的 90 天为准；OI 30 天 cap 以 coverage 记录而非拼接虚构数据

验证窗口以 OKX 可获取的 90 天为准；OI 30 天 cap 以 coverage 记录而非拼接虚构数据

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-06" sid="S-20260806-e21d61e685b118f2" title="meta fetcher 真实 bug 修复（funding dict-as-limit / OI begin+end + info-list 映射 / connect 泄漏）" description="Promoted from run:20260806-001-implement, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004" source="session:20260806-iss-20260804-003-spot-perp:KDC-e21d61e685b118f2">

### meta fetcher 真实 bug 修复（funding dict-as-limit / OI begin+end + info-list 映射 / connect 泄漏）

meta fetcher 真实 bug 修复（funding dict-as-limit / OI begin+end + info-list 映射 / connect 泄漏）

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-06" sid="S-20260806-e373ac2823800028" title="BTC-USDT-SWAP funding 8h 结算 → 90 天仅 270 个结算点" description="Promoted from run:20260806-001-implement, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004" source="session:20260806-iss-20260804-003-spot-perp:KDC-e373ac2823800028">

### BTC-USDT-SWAP funding 8h 结算 → 90 天仅 270 个结算点

BTC-USDT-SWAP funding 8h 结算 → 90 天仅 270 个结算点

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-08" sid="S-20260808-d363ba7c2f0aa2d3" title="per-symbol regime detector" description="Promoted from run:20260808-003-execute, artifact:ART-003-001, artifact:ART-003-002, artifact:ART-003-003, artifact:ART-003-004" source="session:multi-symbol-replay-20260808-20260808-045132:KDC-d363ba7c2f0aa2d3">

### per-symbol regime detector

per-symbol regime detector

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-08" sid="S-20260808-4272fb0f39de12f3" title="SOL from 2021" description="Promoted from run:20260808-002-plan, artifact:ART-002-001, artifact:ART-002-002, artifact:ART-002-003, artifact:ART-002-004, artifact:ART-002-005, artifact:ART-002-006, run:20260808-003-execute, artifact:ART-003-001, artifact:ART-003-002, artifact:ART-003-003, artifact:ART-003-004" source="session:multi-symbol-replay-20260808-20260808-045132:KDC-4272fb0f39de12f3">

### SOL from 2021

SOL from 2021

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-08" sid="S-20260807-ffe5d169f57e64ce" title="OOS/WFO 裁决" description="Promoted from run:20260807-002-plan, artifact:ART-002-001, artifact:ART-002-002, artifact:ART-002-003, artifact:ART-002-004, artifact:ART-002-005, artifact:ART-002-006, artifact:ART-002-007, artifact:ART-002-008, artifact:ART-002-009, run:20260807-003-execute" source="session:mtf-expand-wfo-20260807-20260807-155411:KDC-ffe5d169f57e64ce">

### OOS/WFO 裁决

OOS/WFO 裁决

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-08" sid="S-20260807-bbca142cd8242836" title="排除 1m 与 10m" description="Promoted from run:20260807-002-plan, artifact:ART-002-001, artifact:ART-002-002, artifact:ART-002-003, artifact:ART-002-004, artifact:ART-002-005, artifact:ART-002-006, artifact:ART-002-007, artifact:ART-002-008, artifact:ART-002-009, run:20260807-003-execute" source="session:mtf-expand-wfo-20260807-20260807-155411:KDC-bbca142cd8242836">

### 排除 1m 与 10m

排除 1m 与 10m

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-08" sid="S-20260808-65e48f96fb68cce8" title="禁止 Optuna" description="Promoted from run:20260808-002-plan, artifact:ART-002-001, artifact:ART-002-002, artifact:ART-002-003, artifact:ART-002-004, artifact:ART-002-005, artifact:ART-002-006, artifact:ART-002-007, artifact:ART-002-008, run:20260808-003-execute, artifact:ART-003-001, artifact:ART-003-002, artifact:ART-003-003, artifact:ART-003-004" source="session:nonma-signal-wfo-20260808-20260808-033745:KDC-65e48f96fb68cce8">

### 禁止 Optuna

禁止 Optuna

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-08" sid="S-20260802-0e01c25f603fc736" title="Badge alpha 合成在 gamma sRGB 空间进行" description="Promoted from run:20260802-002-plan, artifact:ART-002-001, run:20260802-003-execute, artifact:ART-003-001" source="session:20260802-maestro-statuswarn-wcag-ci-20260802-075737:KDC-0e01c25f603fc736">

### Badge alpha 合成在 gamma sRGB 空间进行

Badge alpha 合成在 gamma sRGB 空间进行

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-08" sid="S-20260802-61a42ab0c97db631" title="暗色主题 .dark 块不做任何修改" description="Promoted from run:20260802-002-plan, artifact:ART-002-001, run:20260802-003-execute, artifact:ART-003-001" source="session:20260802-maestro-statuswarn-wcag-ci-20260802-075737:KDC-61a42ab0c97db631">

### 暗色主题 .dark 块不做任何修改

暗色主题 .dark 块不做任何修改

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-08" sid="S-20260802-9963e49477a03dc8" title="--warning 与 --status-warn 同步修改（语义耦合）" description="Promoted from run:20260802-002-plan, artifact:ART-002-001, run:20260802-003-execute, artifact:ART-003-001" source="session:20260802-maestro-statuswarn-wcag-ci-20260802-075737:KDC-9963e49477a03dc8">

### --warning 与 --status-warn 同步修改（语义耦合）

--warning 与 --status-warn 同步修改（语义耦合）

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-53b4bf5b0c29d5b9" title="Never merge Path A/B scores; promotion_eligible=false" description="Promoted from run:20260811-002-execute, artifact:ART-002-001, artifact:ART-002-002, artifact:ART-002-003, artifact:ART-002-004, artifact:ART-002-005, artifact:ART-002-006, artifact:ART-002-007, artifact:ART-002-008, report.md#constraint:C-001" source="session:20260811-iaf-adversarial-closeout-20260811-080734:KDC-53b4bf5b0c29d5b9">

### Never merge Path A/B scores; promotion_eligible=false

Never merge Path A/B scores; promotion_eligible=false

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-699cb2167395377f" title="Product HODL gate and anti-overfit CPCV are separate axes; Path B may PASS product and FAIL CPCV" description="Promoted from run:20260811-002-execute, artifact:ART-002-001, artifact:ART-002-002, artifact:ART-002-003, artifact:ART-002-004, artifact:ART-002-005, artifact:ART-002-006, artifact:ART-002-007, artifact:ART-002-008, report.md#decision:D-001" source="session:20260811-iaf-adversarial-closeout-20260811-080734:KDC-699cb2167395377f">

### Product HODL gate and anti-overfit CPCV are separate axes; Path B may PASS product and FAIL CPCV

Product HODL gate and anti-overfit CPCV are separate axes; Path B may PASS product and FAIL CPCV

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-f3ce4c8040c81aed" title="IAF library-only until CPCV prune; no freeze-contract silent edits" description="Promoted from run:20260811-001-analyze, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, report.md#constraint:C-002" source="session:20260811-iaf-adversarial-closeout-20260811-080734:KDC-f3ce4c8040c81aed">

### IAF library-only until CPCV prune; no freeze-contract silent edits

IAF library-only until CPCV prune; no freeze-contract silent edits

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-25da2a0ce94a942e" title="Discrete barrier grids must use optimize_method=grid or fixed entries (no Optuna low/high)" description="Promoted from run:20260811-002-execute, artifact:ART-002-001, artifact:ART-002-002, artifact:ART-002-003, artifact:ART-002-004, artifact:ART-002-005, artifact:ART-002-006, artifact:ART-002-007, artifact:ART-002-008, report.md#constraint:C-002" source="session:20260811-iaf-adversarial-closeout-20260811-080734:KDC-25da2a0ce94a942e">

### Discrete barrier grids must use optimize_method=grid or fixed entries (no Optuna low/high)

Discrete barrier grids must use optimize_method=grid or fixed entries (no Optuna low/high)

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-5db58fe97c5f1938" title="Closeout execute = full run_dual_path_research_os without --skip-validation + pytest + docs refresh" description="Promoted from run:20260811-001-analyze, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, report.md#decision:D-001" source="session:20260811-iaf-adversarial-closeout-20260811-080734:KDC-5db58fe97c5f1938">

### Closeout execute = full run_dual_path_research_os without --skip-validation + pytest + docs refresh

Closeout execute = full run_dual_path_research_os without --skip-validation + pytest + docs refresh

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-a29a494b650a4826" title="Do not re-implement IAF/TPSL cores already on main 3ebf21f" description="Promoted from run:20260811-001-analyze, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, report.md#decision:D-002" source="session:20260811-iaf-adversarial-closeout-20260811-080734:KDC-a29a494b650a4826">

### Do not re-implement IAF/TPSL cores already on main 3ebf21f

Do not re-implement IAF/TPSL cores already on main 3ebf21f

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-6cb8b67ab02c521e" title="Never merge continuous overlay and discrete TPSL into one score" description="Promoted from run:20260811-001-analyze, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, report.md#constraint:C-001" source="session:20260811-iaf-adversarial-closeout-20260811-080734:KDC-6cb8b67ab02c521e">

### Never merge continuous overlay and discrete TPSL into one score

Never merge continuous overlay and discrete TPSL into one score

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-1568e84070eca225" title="promotion_eligible stays false this session" description="Promoted from run:20260811-001-analyze, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, report.md#constraint:C-003" source="session:20260811-iaf-adversarial-closeout-20260811-080734:KDC-1568e84070eca225">

### promotion_eligible stays false this session

promotion_eligible stays false this session

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-c8891798e82a5f4d" title="Closeout keeps dual-path research-only; no live promote" description="Promoted from run:20260811-002-execute, artifact:ART-002-001, artifact:ART-002-002, artifact:ART-002-003, artifact:ART-002-004, artifact:ART-002-005, artifact:ART-002-006, artifact:ART-002-007, artifact:ART-002-008, report.md#decision:D-002" source="session:20260811-iaf-adversarial-closeout-20260811-080734:KDC-c8891798e82a5f4d">

### Closeout keeps dual-path research-only; no live promote

Closeout keeps dual-path research-only; no live promote

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-6572e098bf31c619" title="IAF hard_bind_entry=false always" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, artifact:ART-001-006, report.md#constraint:C-002" source="session:20260811-pathb-iaf-followup-20260811-084339:KDC-6572e098bf31c619">

### IAF hard_bind_entry=false always

IAF hard_bind_entry=false always

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-7c1f6c8c1541a795" title="Allow GO discussion for Path B after multi-window OOS with honest n_trials; still no live promote" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, artifact:ART-001-006, report.md#decision:D-001" source="session:20260811-pathb-iaf-followup-20260811-084339:KDC-7c1f6c8c1541a795">

### Allow GO discussion for Path B after multi-window OOS with honest n_trials; still no live promote

Allow GO discussion for Path B after multi-window OOS with honest n_trials; still no live promote

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-c179d7f26a8cbbd4" title="IAF prune kept factors remain research library after CPCV NO-GO" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, artifact:ART-001-006, report.md#decision:D-002" source="session:20260811-pathb-iaf-followup-20260811-084339:KDC-c179d7f26a8cbbd4">

### IAF prune kept factors remain research library after CPCV NO-GO

IAF prune kept factors remain research library after CPCV NO-GO

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-e17efe1f5095eba7" title="promotion_eligible=false; GO_DISCUSS is research discussion only" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, artifact:ART-001-006, report.md#constraint:C-001" source="session:20260811-pathb-iaf-followup-20260811-084339:KDC-e17efe1f5095eba7">

### promotion_eligible=false; GO_DISCUSS is research discussion only

promotion_eligible=false; GO_DISCUSS is research discussion only

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-391e6909273c1f99" title="Do not re-open completed W14-W26 as greenfield" description="Promoted from run:20260811-001-analyze, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, report.md#constraint:C-001" source="session:20260811-oss-improve-plan-20260811-090327:KDC-391e6909273c1f99">

### Do not re-open completed W14-W26 as greenfield

Do not re-open completed W14-W26 as greenfield

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-45dc964a714d6459" title="no engine rewrite / combined_score / IAF hard-bind / fee loosen" description="Promoted from run:20260811-002-plan, artifact:ART-002-001, artifact:ART-002-002, artifact:ART-002-003, artifact:ART-002-004, artifact:ART-002-005, artifact:ART-002-006, artifact:ART-002-007, artifact:ART-002-008, artifact:ART-002-009, artifact:ART-002-010, artifact:ART-002-011, artifact:ART-002-012, artifact:ART-002-013, artifact:ART-002-014, artifact:ART-002-015, report.md#constraint:C-002" source="session:20260811-oss-improve-plan-20260811-090327:KDC-45dc964a714d6459">

### no engine rewrite / combined_score / IAF hard-bind / fee loosen

no engine rewrite / combined_score / IAF hard-bind / fee loosen

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-6a68e3dadcbc1540" title="No engine rewrite; no combined_score; no IAF hard-bind" description="Promoted from run:20260811-001-analyze, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, report.md#constraint:C-002" source="session:20260811-oss-improve-plan-20260811-090327:KDC-6a68e3dadcbc1540">

### No engine rewrite; no combined_score; no IAF hard-bind

No engine rewrite; no combined_score; no IAF hard-bind

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-f9df6cbdc9a9db31" title="residual-first; do not re-open W14-W26" description="Promoted from run:20260811-002-plan, artifact:ART-002-001, artifact:ART-002-002, artifact:ART-002-003, artifact:ART-002-004, artifact:ART-002-005, artifact:ART-002-006, artifact:ART-002-007, artifact:ART-002-008, artifact:ART-002-009, artifact:ART-002-010, artifact:ART-002-011, artifact:ART-002-012, artifact:ART-002-013, artifact:ART-002-014, artifact:ART-002-015, report.md#constraint:C-001" source="session:20260811-oss-improve-plan-20260811-090327:KDC-f9df6cbdc9a9db31">

### residual-first; do not re-open W14-W26

residual-first; do not re-open W14-W26

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-cef3ee51014134fb" title="Adopt IMP-01 then IMP-02 as next execute priority" description="Promoted from run:20260811-002-plan, artifact:ART-002-001, artifact:ART-002-002, artifact:ART-002-003, artifact:ART-002-004, artifact:ART-002-005, artifact:ART-002-006, artifact:ART-002-007, artifact:ART-002-008, artifact:ART-002-009, artifact:ART-002-010, artifact:ART-002-011, artifact:ART-002-012, artifact:ART-002-013, artifact:ART-002-014, artifact:ART-002-015, report.md#decision:D-001" source="session:20260811-oss-improve-plan-20260811-090327:KDC-cef3ee51014134fb">

### Adopt IMP-01 then IMP-02 as next execute priority

Adopt IMP-01 then IMP-02 as next execute priority

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-e8406607b736b027" title="Prioritize IMP-01 promotion attach + IMP-02 Path B OOS thickness" description="Promoted from run:20260811-001-analyze, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, report.md#decision:D-002" source="session:20260811-oss-improve-plan-20260811-090327:KDC-e8406607b736b027">

### Prioritize IMP-01 promotion attach + IMP-02 Path B OOS thickness

Prioritize IMP-01 promotion attach + IMP-02 Path B OOS thickness

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-a23d6dc5bc873177" title="IMP-03 parallelizable with IMP-01" description="Promoted from run:20260811-002-plan, artifact:ART-002-001, artifact:ART-002-002, artifact:ART-002-003, artifact:ART-002-004, artifact:ART-002-005, artifact:ART-002-006, artifact:ART-002-007, artifact:ART-002-008, artifact:ART-002-009, artifact:ART-002-010, artifact:ART-002-011, artifact:ART-002-012, artifact:ART-002-013, artifact:ART-002-014, artifact:ART-002-015, report.md#decision:D-002" source="session:20260811-oss-improve-plan-20260811-090327:KDC-a23d6dc5bc873177">

### IMP-03 parallelizable with IMP-01

IMP-03 parallelizable with IMP-01

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-e7af89d3d61a773b" title="Produce IMP-* residual improvement plan (plan stage)" description="Promoted from run:20260811-001-analyze, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, report.md#decision:D-001" source="session:20260811-oss-improve-plan-20260811-090327:KDC-e7af89d3d61a773b">

### Produce IMP-* residual improvement plan (plan stage)

Produce IMP-* residual improvement plan (plan stage)

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-f589ad4d5480b92c" title="no combined_score; no engine rewrite" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, report.md#constraint:C-002" source="session:20260811-imp01-02-exec-20260811-091927:KDC-f589ad4d5480b92c">

### no combined_score; no engine rewrite

no combined_score; no engine rewrite

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-c1227b888e904430" title="IMP-02 default n_windows=6 with fee_slip_grid+funding_tca assumption" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, report.md#decision:D-002" source="session:20260811-imp01-02-exec-20260811-091927:KDC-c1227b888e904430">

### IMP-02 default n_windows=6 with fee_slip_grid+funding_tca assumption

IMP-02 default n_windows=6 with fee_slip_grid+funding_tca assumption

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-dfdad156f5b9404b" title="Research dual-path claims vectorized path honestly rather than fake paper_replay" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, report.md#decision:D-001" source="session:20260811-imp01-02-exec-20260811-091927:KDC-dfdad156f5b9404b">

### Research dual-path claims vectorized path honestly rather than fake paper_replay

Research dual-path claims vectorized path honestly rather than fake paper_replay

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-0c5feae00cc4c7d4" title="promotion_eligible=false; vectorized is not register-ready" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, report.md#constraint:C-001" source="session:20260811-imp01-02-exec-20260811-091927:KDC-0c5feae00cc4c7d4">

### promotion_eligible=false; vectorized is not register-ready

promotion_eligible=false; vectorized is not register-ready

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-e1c94993e5585fd9" title="Reuse existing FeatureStore PIT tests; add pit_audit helper" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, report.md#decision:D-001" source="session:20260811-imp03-05-exec-20260811-093415:KDC-e1c94993e5585fd9">

### Reuse existing FeatureStore PIT tests; add pit_audit helper

Reuse existing FeatureStore PIT tests; add pit_audit helper

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-09247aabe8ae530d" title="Multi-symbol dual-path equal book weights display-only" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, report.md#decision:D-002" source="session:20260811-imp03-05-exec-20260811-093415:KDC-09247aabe8ae530d">

### Multi-symbol dual-path equal book weights display-only

Multi-symbol dual-path equal book weights display-only

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-2d2429a1d6c202a2" title="no combined_score; no multi-exchange; no live promote" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, report.md#constraint:C-001" source="session:20260811-imp03-05-exec-20260811-093415:KDC-2d2429a1d6c202a2">

### no combined_score; no multi-exchange; no live promote

no combined_score; no multi-exchange; no live promote

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-2307c60010637468" title="Untrack .workflow/scratch runtime junk from remote" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, report.md#decision:D-002" source="session:20260811-cleanup-release-070-20260811-102622:KDC-2307c60010637468">

### Untrack .workflow/scratch runtime junk from remote

Untrack .workflow/scratch runtime junk from remote

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-84fb484bf75f0412" title="Bump minor 0.6.0→0.7.0 for IMP residual research OS" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, report.md#decision:D-001" source="session:20260811-cleanup-release-070-20260811-102622:KDC-84fb484bf75f0412">

### Bump minor 0.6.0→0.7.0 for IMP residual research OS

Bump minor 0.6.0→0.7.0 for IMP residual research OS

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-ae40629038b5966b" title="no force-push; no secrets; no live promote" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, report.md#constraint:C-001" source="session:20260811-cleanup-release-070-20260811-102622:KDC-ae40629038b5966b">

### no force-push; no secrets; no live promote

no force-push; no secrets; no live promote

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-2be914ab41c82659" title="Broken wiki links FP leave sealed sessions untouched" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, report.md#constraint:C-002" source="session:20260811-kb-maint-20260811-105226:KDC-2be914ab41c82659">

### Broken wiki links FP leave sealed sessions untouched

Broken wiki links FP leave sealed sessions untouched

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-56ac92356f6e5c2d" title="Add DOC IMP residual research OS + TIP pending_observed policy; link from hub" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, report.md#decision:D-001" source="session:20260811-kb-maint-20260811-105226:KDC-56ac92356f6e5c2d">

### Add DOC IMP residual research OS + TIP pending_observed policy; link from hub

Add DOC IMP residual research OS + TIP pending_observed policy; link from hub

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-5e7a3a193d473c8c" title="kg sync sufficient; no rebuild" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, report.md#decision:D-002" source="session:20260811-kb-maint-20260811-105226:KDC-5e7a3a193d473c8c">

### kg sync sufficient; no rebuild

kg sync sufficient; no rebuild

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-ca1bec8ea05c8d81" title="Do not mass-promote uncorroborated pending_observed" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, report.md#constraint:C-001" source="session:20260811-kb-maint-20260811-105226:KDC-ca1bec8ea05c8d81">

### Do not mass-promote uncorroborated pending_observed

Do not mass-promote uncorroborated pending_observed

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-d864e7a891f5d425" title="No backfill/forge streak days" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, artifact:ART-001-006, artifact:ART-001-007, report.md#constraint:C-001" source="session:20260811-t023-ops-20260811-112304:KDC-d864e7a891f5d425">

### No backfill/forge streak days

No backfill/forge streak days

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-6c49109795969619" title="Run T024 dry-run while short to prove fail-closed floors" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, artifact:ART-001-006, artifact:ART-001-007, report.md#decision:D-002" source="session:20260811-t023-ops-20260811-112304:KDC-6c49109795969619">

### Run T024 dry-run while short to prove fail-closed floors

Run T024 dry-run while short to prove fail-closed floors

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-6c586f79e2f3b6c5" title="No live promote without human authorization" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, artifact:ART-001-006, artifact:ART-001-007, report.md#constraint:C-002" source="session:20260811-t023-ops-20260811-112304:KDC-6c586f79e2f3b6c5">

### No live promote without human authorization

No live promote without human authorization

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-9e130f8a12708897" title="Credit 2026-08-11 after PREFLIGHT OK day-session only" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, artifact:ART-001-006, artifact:ART-001-007, report.md#decision:D-001" source="session:20260811-t023-ops-20260811-112304:KDC-9e130f8a12708897">

### Credit 2026-08-11 after PREFLIGHT OK day-session only

Credit 2026-08-11 after PREFLIGHT OK day-session only

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-ce2679d2ed4a8f0d" title="Treat Path B validation NO-GO and OOS GO_DISCUSS as successful system verification" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, artifact:ART-001-006, artifact:ART-001-007, artifact:ART-001-008, artifact:ART-001-009, artifact:ART-001-010, report.md#decision:D-002" source="session:20260811-mkt-cap-verify-20260811-113906:KDC-ce2679d2ed4a8f0d">

### Treat Path B validation NO-GO and OOS GO_DISCUSS as successful system verification

Treat Path B validation NO-GO and OOS GO_DISCUSS as successful system verification

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-66e3aa726ba549db" title="No combined_score" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, artifact:ART-001-006, artifact:ART-001-007, artifact:ART-001-008, artifact:ART-001-009, artifact:ART-001-010, report.md#constraint:C-002" source="session:20260811-mkt-cap-verify-20260811-113906:KDC-66e3aa726ba549db">

### No combined_score

No combined_score

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-79f3ebde51e2aa82" title="Use full contract window 2021-01-01..2026-08-04 offline parquet as capability proof" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, artifact:ART-001-006, artifact:ART-001-007, artifact:ART-001-008, artifact:ART-001-009, artifact:ART-001-010, report.md#decision:D-001" source="session:20260811-mkt-cap-verify-20260811-113906:KDC-79f3ebde51e2aa82">

### Use full contract window 2021-01-01..2026-08-04 offline parquet as capability proof

Use full contract window 2021-01-01..2026-08-04 offline parquet as capability proof

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-8ebd3489a8edc6bc" title="No live promote; promotion_eligible remains false" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, artifact:ART-001-006, artifact:ART-001-007, artifact:ART-001-008, artifact:ART-001-009, artifact:ART-001-010, report.md#constraint:C-001" source="session:20260811-mkt-cap-verify-20260811-113906:KDC-8ebd3489a8edc6bc">

### No live promote; promotion_eligible remains false

No live promote; promotion_eligible remains false

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-f78780b964f3774e" title="No combined_score; no live promote" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, artifact:ART-001-006, artifact:ART-001-007, artifact:ART-001-008, artifact:ART-001-009, report.md#constraint:C-003" source="session:20260811-perf-metrics-20260811-120059:KDC-f78780b964f3774e">

### No combined_score; no live promote

No combined_score; no live promote

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-3e9e2dedab6bb9d3" title="Reuse locked B0 WFO/gate; re-run full-window confirmed numeric match" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, artifact:ART-001-006, artifact:ART-001-007, artifact:ART-001-008, artifact:ART-001-009, report.md#decision:D-002" source="session:20260811-perf-metrics-20260811-120059:KDC-3e9e2dedab6bb9d3">

### Reuse locked B0 WFO/gate; re-run full-window confirmed numeric match

Reuse locked B0 WFO/gate; re-run full-window confirmed numeric match

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-88b6c209b7cadfd8" title="Silo risk_parity not comparable 1:1 to shared book" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, artifact:ART-001-006, artifact:ART-001-007, artifact:ART-001-008, artifact:ART-001-009, report.md#constraint:C-002" source="session:20260811-perf-metrics-20260811-120059:KDC-88b6c209b7cadfd8">

### Silo risk_parity not comparable 1:1 to shared book

Silo risk_parity not comparable 1:1 to shared book

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-a5fe3e2706e0ef21" title="Parity only paper↔live; vectorized research not promotion-eligible" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, artifact:ART-001-006, artifact:ART-001-007, artifact:ART-001-008, artifact:ART-001-009, report.md#constraint:C-001" source="session:20260811-perf-metrics-20260811-120059:KDC-a5fe3e2706e0ef21">

### Parity only paper↔live; vectorized research not promotion-eligible

Parity only paper↔live; vectorized research not promotion-eligible

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-b48ad559cfc3f47b" title="Use multi_symbol_replay full window as primary portfolio performance panel" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, artifact:ART-001-006, artifact:ART-001-007, artifact:ART-001-008, artifact:ART-001-009, report.md#decision:D-001" source="session:20260811-perf-metrics-20260811-120059:KDC-b48ad559cfc3f47b">

### Use multi_symbol_replay full window as primary portfolio performance panel

Use multi_symbol_replay full window as primary portfolio performance panel

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-eea51789e34ff16d" title="Land IMP-06 via test_imp06_hard_bind_lock.py" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, report.md#decision:D-003" source="session:20260811-learn-opt-struct-20260811-124137:KDC-eea51789e34ff16d">

### Land IMP-06 via test_imp06_hard_bind_lock.py

Land IMP-06 via test_imp06_hard_bind_lock.py

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-61fd2baf5a9748b8" title="No combined_score; B0 freeze untouched" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, report.md#constraint:C-003" source="session:20260811-learn-opt-struct-20260811-124137:KDC-61fd2baf5a9748b8">

### No combined_score; B0 freeze untouched

No combined_score; B0 freeze untouched

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-b0a80762d62f2293" title="Do not re-sweep overlay_weight away from 0.30 without new cost matrix evidence" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, report.md#constraint:C-001" source="session:20260811-learn-opt-struct-20260811-124137:KDC-b0a80762d62f2293">

### Do not re-sweep overlay_weight away from 0.30 without new cost matrix evidence

Do not re-sweep overlay_weight away from 0.30 without new cost matrix evidence

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-c1055a8731dca0cf" title="Export dual-path research surface from quantflow.strategy.research" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, report.md#decision:D-002" source="session:20260811-learn-opt-struct-20260811-124137:KDC-c1055a8731dca0cf">

### Export dual-path research surface from quantflow.strategy.research

Export dual-path research surface from quantflow.strategy.research

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-c52d933ce0a1e6cb" title="Optimize structure and regression locks rather than alpha re-search this session" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, report.md#decision:D-001" source="session:20260811-learn-opt-struct-20260811-124137:KDC-c52d933ce0a1e6cb">

### Optimize structure and regression locks rather than alpha re-search this session

Optimize structure and regression locks rather than alpha re-search this session

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-d1651d9fe4f9d813" title="hard_bind_entry must remain false on research OS surfaces" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, report.md#constraint:C-002" source="session:20260811-learn-opt-struct-20260811-124137:KDC-d1651d9fe4f9d813">

### hard_bind_entry must remain false on research OS surfaces

hard_bind_entry must remain false on research OS surfaces

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-8441f2ce8b9f05da" title="Catalog skips *_overlay.yaml and rejects duplicate strategy.name" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, report.md#decision:D-002" source="session:20260811-catalog-imp-20260811-130143:KDC-8441f2ce8b9f05da">

### Catalog skips *_overlay.yaml and rejects duplicate strategy.name

Catalog skips *_overlay.yaml and rejects duplicate strategy.name

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-10f46a601a583b33" title="No live promote; no combined_score; no B0 freeze edit" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, report.md#constraint:C-002" source="session:20260811-catalog-imp-20260811-130143:KDC-10f46a601a583b33">

### No live promote; no combined_score; no B0 freeze edit

No live promote; no combined_score; no B0 freeze edit

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,constraint" date="2026-08-11" sid="S-20260811-12c971c743bb8aad" title="Research overlays must not live as strategies/*_overlay.yaml catalog peers" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, report.md#constraint:C-001" source="session:20260811-catalog-imp-20260811-130143:KDC-12c971c743bb8aad">

### Research overlays must not live as strategies/*_overlay.yaml catalog peers

Research overlays must not live as strategies/*_overlay.yaml catalog peers

</spec-entry>

<spec-entry category="arch" keywords="session-knowledge,decision" date="2026-08-11" sid="S-20260811-47dac3bef01949b5" title="Move funding B4/B5 overlays to quantflow/config/research/overlays/" description="Promoted from run:20260811-001-execute, artifact:ART-001-001, artifact:ART-001-002, artifact:ART-001-003, artifact:ART-001-004, artifact:ART-001-005, report.md#decision:D-001" source="session:20260811-catalog-imp-20260811-130143:KDC-47dac3bef01949b5">

### Move funding B4/B5 overlays to quantflow/config/research/overlays/

Move funding B4/B5 overlays to quantflow/config/research/overlays/

</spec-entry>