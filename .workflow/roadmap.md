# Roadmap: QuantFlow 策略扩展与发布准备

## Overview

当前 roadmap 分为两个阶段：

- `M1` 已完成：4 个新增策略的实现与验证
- `M2` 进行中：`v0.1.3` 发布候选准备，目标是对齐版本、治理打包内容、重建制品校验信息，并为后续 tag / release 对齐铺平状态
- `M3` 进行中：按 deep-research 研究文档（ANL-002）分批里程碑实施 P0 数据层防泄漏 → P1 风控层补齐 → P2 AI 层升级，每批独立实盘验证后才进下一批。**P0 代码层完成**，**P1 已 P1-verify PASS（2026-07-21，commit `626b015`）**，**P2 unblocked 未启动**（P2.1 schema-only 隔离层为下一步）。2026-07-25 另完成 Wave 1-5 多 book reconcile 一致性收口（L4 单一权威 + L5 薄路由 + realized_pnl 翻仓归因 + daily_loss total-vs-baseline + partial-fill cumulative 契约）——该 reconcile 契约现为新 load-bearing 架构不变量，后续成功标准须引用（drift-realign DFT-6f8d5a9b, 2026-07-26）

## Milestones

### Milestone 1: 四策略实现（v1.1）

**Target**：交付 4 个新策略，含代码、配置、测试与 CLI 接线  
**Status**：completed

#### Phases

- [x] **Phase 1: 策略实现与验证**：实现 P1-P4 四个策略，并补全 YAML 配置、单元测试、CLI 接线

#### Delivery Summary

- [x] `VolatilityBreakoutStrategy`
- [x] `FundingRateStrategy`
- [x] `MomentumRotationStrategy`
- [x] `MLEnsembleStrategy`
- [x] `quantflow research --strategy <name>` 接线完成
- [x] `quantflow optimize --strategy <name>` 参数空间接线完成
- [x] `quantflow validate --strategy <name>` 验证入口接线完成
- [x] 对应测试文件已落地并通过

#### Verification

- 单测结果：`37 passed`
- 覆盖内容：
  - 新策略参数初始化
  - `on_bar()` 基本行为
  - `generate_signals()` 输出形态
  - Cross-sectional / ML / funding data 等特殊逻辑
  - CLI 命令帮助与基本入口

### Milestone 2: v0.1.3 发布候选准备

**Target**：建立干净、可复现、可对齐 tag / release 的 `v0.1.3` 发布候选  
**Status**：in_progress

#### Phases

- [x] **Phase 1: 版本与工作流对齐**：更新版本元数据，建立发布里程碑与 maestro 会话，准备 `docs/release/v0.1.3/`
- [x] **Phase 2: 打包治理与制品重建**：限制 sdist / wheel 内容，重建 `SHA256SUMS.txt` 与 `release-manifest.json`
- [x] **Phase 3: 发布证据与远端对齐**：tag `v0.1.3` + GitHub Release「QuantFlow v0.1.3」已创建（commit `4bc72cd`，2026-06-07），dist 制品已封存

#### Delivery Summary

- [x] `pyproject.toml` 与 `quantflow/__init__.py` 对齐到 `0.1.3`
- [x] `.workflow/state.json` 与 `.workflow/.maestro/.../status.json` 建立发布推进状态
- [x] `docs/release/v0.1.3/` 文档集存在且与当前候选版本一致
- [x] `sdist` 排除 `.workflow`、`.codegraph`、`tests`、缓存与运行态内容
- [x] `dist/quantflow-0.1.3.tar.gz`
- [x] `dist/quantflow-0.1.3-py3-none-any.whl`
- [x] `dist/quantflow-0.1.3.tar.gz.sha256`
- [x] `dist/quantflow-0.1.3-py3-none-any.whl.sha256`
- [x] `dist/SHA256SUMS.txt`
- [x] `dist/release-manifest.json`

#### Blocking Findings

- ~~`v0.1.3` 远端 tag / release 尚未创建~~ — **已解决**：tag `v0.1.3`（target `4bc72cd`）+ GitHub Release「QuantFlow v0.1.3」已创建于 2026-06-07（drift-realign DFT-4d1a3b69, 2026-07-26）
- ~~安全扫描与发布证据仍未归档~~ — 待核验：远端资产闭环扫描证据归档状态未确认（保留待办）

### Milestone 3: deep-research 改进分批实施（P0/P1/P2）

**Target**：按 ANL-002 分析结论分三批实施 deep-research 验证的 10 条改进，每批独立实盘验证后才进下一批
**Status**：in_progress
**Upstream**：ANL-002（analyze-macro，scope=large，GO_CONDITIONAL 88%）、GRL-001（grill）、deep-research-20260718（15 findings，24/25 verified）

#### 串行硬约束

P0 实盘验证通过 → P1 启动；P1 实盘验证通过 → P2 启动。批次间禁止并行（3 独立子系统跨 L1/L2/L3/L4 + 串行验证约束）。

#### Phase 1: P0 数据层防泄漏（milestone-gate: P0-verify）

**Status**：代码层完成，待 P0-verify（产出 `verification.json` + 回测回归守卫证据）

**Scope**：F1 MTF look-ahead 核实+修复、F2 look-ahead 检测 CLI
**Target files**：`mtf_aligner.py:139-177`、`fetcher.py:63-110`、`cli/main.py:288-439`、`strategy/validation/lookahead.py`（新建）、`tests/`

**Tasks**:
- [x] **P0.0 只读核实**：读 `_create_aligned_index` + 写「跨 HTF 边界 minor bar 断言无未收盘 HTF 值泄漏」测试。核实结论：CCXT fetch_ohlcv 返回 bar-open 时间戳（fetcher.py:102-105），原 reindex+ffill 会暴露未收盘 HTF bar → 确认泄漏存在，进 P0.1
- [x] **P0.1 MTF 修复（方案 b）**：reindex 前将 HTF index 整体右移一个周期（`_infer_period` 三级推断：freq → infer_freq → median diff），HTF bar 值只在下一根开盘（== 本根收盘）后对 minor 可见；不改 fetcher 索引，不破坏 backtest parity — commit `01f05fb`
- [x] **P0.2 look-ahead CLI**：`quantflow validate --method lookahead` 新建 `validation/lookahead.py`，静态 AST 扫描检出 `series[mask].agg()` 聚合泄漏模式（Shape 1 high / Shape 2 medium），无需数据/回测可直接进 CI — commit `99795b2`
- [ ] **P0.3 回归守卫**：4 策略回测基线 byte-for-byte 不变 — ⚠️ Wave 1-5（2026-07-25）重写 `strategy/engine.py`+`execution/engine.py`，pre-Wave 基线已失效，须对当前 HEAD 重立 `test-results.json`（drift-realign DFT-5e7c4f8a, 2026-07-26）

**Acceptance**:
- MTF 跨 HTF 边界无未收盘值泄漏断言通过 ✅（`test_mtf_does_not_expose_unclosed_htf_bar_close_to_minor`）
- look-ahead CLI 能检出已知泄漏模式 ✅（12 测试覆盖 clean/leaky/链式去重/分级/真实策略零误报）
- 4 策略回测无回归 — 待 P0-verify

**Done when**: `verification.json` passed + `test-results.json` 泄漏断言绿

#### Phase 2: P1 风控层补齐（milestone-gate: P1-verify）

**Status**：P1-verify PASS（2026-07-21，commit `626b015`）— F3/F4 GO，F5 mean_reversion 路径运气红旗 ISS-20260720-003 为「诊断非 gate」不阻 P2

**Scope**：F3 vol-targeting（opt-in）、F4 辅助诊断 CVaR、F5 路径级 MC 压力测试
**Target files**：`config.py:50-68`、`position_sizer.py:12-99`、`risk_metrics.py:13-62`、`risk_engine.py:176-193`、`strategy/validation/monte_carlo.py`（新建）、`cli/main.py`

**关键修正（ANL-002 claude delegate）**：F4「MC CVaR 替代主 gate historical CVaR」是**反模式**（parametric 违反 fat-tail arch spec，bootstrap 与 historical 渐近等价）→ F4 改为辅助诊断指标，**真正增量是 F5 路径级 MC 压力测试**（trade-order shuffling + candles-based，仿 Jesse）。

**Tasks**:
- [x] **P1.1 vol-target opt-in**：`RiskConfig` 加 `vol_target_pct`（默认 off），`PositionSizer` 加 vol-target method，绑定 `仓位=min(half-Kelly, vol-target, 单名上限)` — commit `09445de`
- [x] **P1.2 MC 压力测试**：新建 `validation/monte_carlo.py`，trade-shuffle + returns-bootstrap 两法（candles-based 因 vectorbt 移除改 returns-bootstrap），诊断非 gate — commit `9b856ff`
- [x] **P1.3 辅助 CVaR**：`risk_metrics` 加 `bootstrap_cvar` 作辅助诊断（非主 gate，不替代 historical CVaR） — commit `5e5b432`
- [x] **P1.4 CLI**：`quantflow validate --method stress` — commit `9b856ff`
- [x] **P1.5 回归守卫**：默认 off 时 byte-for-byte 不变（`test_default_off_is_byte_for_byte_baseline` + 全量 1411 passed，唯一失败为预存 FeatureStore pandas3.14 超界，与 P1 无关）
- [x] **P1.0-B1 阻塞修复**：`add_return` 零调用方导致 `_returns_history` 永空 → `engine.on_bar` 接线 `bar_ret = (curr_equity - prev_equity)/prev_equity`（pre-mark 捕获，无 look-ahead），喂给 `risk_engine.add_return` + `position_sizer.add_return`，8 单测覆盖历史填充与 gate 触发；CVaR gate 现真正生效 — commit `ec17b23`（issue 登记 `82331b4`，ISS-20260719-001 resolved）
- [x] **P1.6 parity 地基（P1-verify 前置）**：F3 用 paper-on_bar、F5 用 BacktestEngine 跑，两路径信号必须 parity 否则 verify 结论不可信
  - parity 守卫 `TestSignalParityGuard`（commit `4c2dbd0`）：逐 bar 比对 `_latest_signal` vs `generate_signals`，ENTRY 0 漂移（5/5 seed）
  - F4/F5 数据流接通（commit `4f5e218`）：paper session 的 `_risk_engine._returns_history` 可直接喂 `bootstrap_cvar` + `monte_carlo_stress(bar_returns=)`，纯 list 接口无需改代码
  - paper 历史回放脚本（commit `ce4d9b4`）：`scripts/replay_paper_f4f5.py` 回放本地 parquet 经 on_bar 积累 F4/F5 诊断数据
  - **ISS-20260613-006 exit 漂移根因修复**（commit `0dbee17`）：`generate_signals` exit 此前用 `short_count`（含 vol_ok + 阈值 min_conditions）与 `_latest_signal` 的 `exit_count`（无 vol_ok + 阈值 min_conditions-1）不一致，违反 `# exit without vol_ok` 设计意图 → 对齐为无 vol_ok + 阈值 min_conditions-1；守卫 `test_exit_residual_is_profit_trailing_role_difference` 确认条件 exit 漂移消除（12..22→1..16），残留单向 shape = profit/trailing 合并的职责差异非 bug
  - **regime 维度 parity 缺口登记**（commit `0dbee17`）：on_bar 应用 regime gating（ADX>=25），`generate_signals` 不应用 → 实测真实 BTC/USDT 1h 全 84 entries 落非 trending bar → on_bar 全 gate → 回测交易 84 次/实盘 0 次。根因 entry 用 MA 方向 vs regime 用 ADX 强度，direction!=strength。设计冲突非 bug，`TestRegimeParityGap` 守卫量化固化，待人裁决 regime↔entry 对齐方向（比 ISS-006 exit 更结构性）
  - checklist 三步结论（commit `3cfda6a` + `805e5b7`）：离线/模拟实盘可执行性确认，parity 地基 + F5 输入源 + 回放工具就绪

**Acceptance（代码层）**:
- 仓位绑定规则 opt-in 生效（高波动区间 vol-target < Kelly，低波动区间不绑定）✅
- MC 压力测试接入 CLI `--method stress`（诊断 method，不动 GO/NO-GO）✅
- 默认 off 时 4 策略回测 byte-for-byte 不变 ✅
- `add_return` 接线后 `_returns_history` 真实累积，CVaR gate 历史 ≥30 时真正阻断 ✅

**Acceptance（实盘 verify，待）**：按 `.workflow/specs/p1-live-verification-checklist.md`，F3 缩仓行为 / F5 路径运气红旗 / F4 CI 收窄在实盘数据上复现，全 GO/NO-GO 项 PASS + 两「诊断非 gate」契约项 PASS。

**Deferred**：研究层大规模参数扫描优化（依赖 F8 vectorbt 裁决——「numpy 向量化并行」vs「重新评估 vectorbt 2026 兼容性」，用户 P1 启动前裁决）

**Done when**: ✅ P1-verify `verification.json` + `review.json` passed（checklist 全 PASS，2026-07-21，commit `626b015`）

#### Phase 3: P2 AI 层升级（milestone-gate: P2-verify）

**Status**：unblocked（P1-verify PASS 2026-07-21），未启动 — P2.1 schema-only 隔离层是下一步；串行约束闸门已开（drift-realign DFT-2b8e1d47, 2026-07-26）
**Scope**：F6 schema-only 暴露层（P2 内部硬约束）、F11 FinGPT、F12 情绪传播广度
**Target files**：`strategy/sentiment.py`、新建 schema 暴露层

**Tasks**:
- [ ] **P2.1 schema-only 隔离层**：新建 schema 暴露层屏蔽原始市场数据 + train/val/test 时间分割边界，LLM 只看 schema 不看数据值/时间点（RD-Agent(Q) NeurIPS 2025 范式，先于真实 LLM loop）
- [ ] **P2.2 FinBERT→FinGPT 升级**：单卡 RTX 3090/$17.25 微调路径（medium-high，2-1 vote，自报基准）
- [ ] **P2.3 情绪传播广度**：`SentimentAnalyzer.analyze` 接收传播广度元数据（聚类触达+影响力注入 prompt，+8 百分点，AAAI 2025）

**Acceptance**:
- schema-only 隔离层屏蔽原始数据/时间分割
- 情绪 analyze 接收传播广度元数据

**Done when**: `verification.json` + `review.json` passed

#### Phase 4: 多 book reconcile 一致性收口（Wave 1-5，2026-07-25 已落地）

**Status**：completed（commits `7e781a8` → `06a8d93`，Wave 1-5，2026-07-25）

**Scope**：横切 L4/L5 执行路径一致性重构 — 消除多账本、统一 fill 更新点、翻仓 realized 归因、daily_loss 语义切换、partial-fill cumulative 契约。此 Phase 非 deep-research F1-F12 范畴，是 P1-verify 后暴露的执行路径一致性收口（drift-realign DFT-3c9f2e58 补登，2026-07-26）。

**Tasks（已落地）**:
- [x] **Wave 1**：`PortfolioManager` 增 `realized_pnl` 翻仓归因（closing-leg PnL）+ `daily_baseline` 字段 — commit `7e781a8`
- [x] **Wave 2**：`PositionManager` 退化为薄路由委托 L4（全 9 方法委托 + `bind_portfolio`），`PaperGateway` 移除第三套 `_cash` 账本 — commit `062a7b5`
- [x] **Wave 3**：`daily_loss` gate 改 total-vs-baseline 语义（日切首 bar equity 锚定），替代旧 daily PnL 累计 — commit `90b3eff`
- [x] **Wave 4**：partial-fill cumulative 契约 — `Order.applied_filled_qty` + `delta_filled` guard（POSITION_EPSILON 防 0 回调误调 L4），OKX cumulative fill 提取 — commit `b0177e0`
- [x] **Wave 5**：全套验证通过（lint + mypy + test + parity） — commit `06a8d93`

**Acceptance**:
- L4 PortfolioManager 单一权威账本，engine.submit 统一 fill 更新点（含 fee），_process_signal 不再二次更新 L4 ✅
- L5 PositionManager 薄路由委托，PaperGateway 无独立 cash 账本 ✅
- paper/live 经同一 engine.submit 路径，parity 成立（backtest 独立向量化 book 不在 reconcile 范围，per arch parity spec）✅
- partial-fill 重复回调不双计 L4 ✅

**Done when**: ✅ Wave 5 全套验证通过（2026-07-25，commit `06a8d93`）

**Note（drift-realign DFT-5e7c4f8a）**：Wave 1-5 重写了 `strategy/engine.py`（+57）与 `execution/engine.py`（+111），P0.3 byte-for-byte 回归守卫基线若在 Wave 前建立则已失效，需对当前 HEAD 重立基线。

## Scope Decisions

- **In scope**：版本抬升到 `v0.1.3`、发布文档、`.workflow` 发布里程碑、maestro 会话、打包治理、哈希与 manifest 刷新
- **Deferred**：GitHub tag / release 真实发布、远端资产上传、paper / live 运行证据补齐
- **Out of scope**：新增 Gateway、新数据源、前端 UI、部署拓扑重构

## Progress

| Milestone | Phase | Status | Completed |
|-----------|-------|--------|-----------|
| 1. 四策略实现 | 1. 策略实现与验证 | Completed | 2026-06-02 |
| 2. v0.1.3 发布候选准备 | 1. 版本与工作流对齐 | Completed | 2026-06-07 |
| 2. v0.1.3 发布候选准备 | 2. 打包治理与制品重建 | Completed | 2026-06-07 |
| 2. v0.1.3 发布候选准备 | 3. 发布证据与远端对齐 | Completed | 2026-06-07 (tag `4bc72cd` + Release) |
| 3. deep-research 改进分批实施 | 1. P0 数据层防泄漏 | 代码完成，待 P0-verify（P0.3 基线待 Wave 后重立） | `01f05fb` `99795b2` |
| 3. deep-research 改进分批实施 | 2. P1 风控层补齐 | **P1-verify PASS** | 2026-07-21 `626b015` |
| 3. deep-research 改进分批实施 | 2.5 多 book reconcile (Wave 1-5) | **Completed** | 2026-07-25 `7e781a8`→`06a8d93` |
| 3. deep-research 改进分批实施 | 3. P2 AI 层升级 | Unblocked，未启动 | - |
