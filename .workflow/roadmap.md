# Roadmap: QuantFlow 策略扩展与发布准备

## Overview

当前 roadmap 分为两个阶段：

- `M1` 已完成：4 个新增策略的实现与验证
- `M2` 进行中：`v0.1.3` 发布候选准备，目标是对齐版本、治理打包内容、重建制品校验信息，并为后续 tag / release 对齐铺平状态
- `M3` 规划中：按 deep-research 研究文档（ANL-002）分批里程碑实施 P0 数据层防泄漏 → P1 风控层补齐 → P2 AI 层升级，每批独立实盘验证后才进下一批

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
- [ ] **Phase 3: 发布证据与远端对齐**：准备 tag / release 对齐所需证据，核验远端资产闭环

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

- `v0.1.3` 远端 tag / release 尚未创建
- 安全扫描与发布证据仍未归档到当前候选版本

### Milestone 3: deep-research 改进分批实施（P0/P1/P2）

**Target**：按 ANL-002 分析结论分三批实施 deep-research 验证的 10 条改进，每批独立实盘验证后才进下一批
**Status**：planned
**Upstream**：ANL-002（analyze-macro，scope=large，GO_CONDITIONAL 88%）、GRL-001（grill）、deep-research-20260718（15 findings，24/25 verified）

#### 串行硬约束

P0 实盘验证通过 → P1 启动；P1 实盘验证通过 → P2 启动。批次间禁止并行（3 独立子系统跨 L1/L2/L3/L4 + 串行验证约束）。

#### Phase 1: P0 数据层防泄漏（milestone-gate: P0-verify）

**Scope**：F1 MTF look-ahead 核实+修复、F2 look-ahead 检测 CLI
**Target files**：`mtf_aligner.py:139-177`、`fetcher.py:63-110`、`cli/main.py:288-439`、`strategy/validation/lookahead.py`（新建）、`tests/`

**Tasks**:
- [ ] **P0.0 只读核实**：读 `_create_aligned_index` + 写「跨 HTF 边界 minor bar 断言无未收盘 HTF 值泄漏」测试，用证据决定是否进 P0.1（grill Q1.2 locked：禁止在核实前修改 mtf_aligner）
- [ ] **P0.1 MTF 修复（方案 b）**：aligner 层只 ffill 已收盘 HTF bar（最小改动，不改 fetcher 索引，不破坏 backtest parity）
- [ ] **P0.2 look-ahead CLI**：`quantflow validate --method lookahead` 新建 `validation/lookahead.py`，检出 `series[entries].mean()` 聚合泄漏模式（仿 Freqtrade lookahead-analysis）
- [ ] **P0.3 回归守卫**：4 策略回测基线 byte-for-byte 不变

**Acceptance**:
- MTF 跨 HTF 边界无未收盘值泄漏断言通过
- look-ahead CLI 能检出已知泄漏模式
- 4 策略回测无回归

**Done when**: `verification.json` passed + `test-results.json` 泄漏断言绿

#### Phase 2: P1 风控层补齐（milestone-gate: P1-verify）

**Scope**：F3 vol-targeting（opt-in）、F4 辅助诊断 CVaR、F5 路径级 MC 压力测试
**Target files**：`config.py:50-68`、`position_sizer.py:12-99`、`risk_metrics.py:13-62`、`risk_engine.py:176-193`、`strategy/validation/monte_carlo.py`（新建）、`cli/main.py`

**关键修正（ANL-002 claude delegate）**：F4「MC CVaR 替代主 gate historical CVaR」是**反模式**（parametric 违反 fat-tail arch spec，bootstrap 与 historical 渐近等价）→ F4 改为辅助诊断指标，**真正增量是 F5 路径级 MC 压力测试**（trade-order shuffling + candles-based，仿 Jesse）。

**Tasks**:
- [x] **P1.1 vol-target opt-in**：`RiskConfig` 加 `vol_target_pct`（默认 off），`PositionSizer` 加 vol-target method，绑定 `仓位=min(half-Kelly, vol-target, 单名上限)` — commit `09445de`
- [x] **P1.2 MC 压力测试**：新建 `validation/monte_carlo.py`，trade-shuffle + returns-bootstrap 两法（candles-based 因 vectorbt 移除改 returns-bootstrap），诊断非 gate — commit `9b856ff`
- [x] **P1.3 辅助 CVaR**：`risk_metrics` 加 `bootstrap_cvar` 作辅助诊断（非主 gate，不替代 historical CVaR） — commit `5e5b432`
- [x] **P1.4 CLI**：`quantflow validate --method stress` — commit `9b856ff`
- [x] **P1.5 回归守卫**：默认 off 时 byte-for-byte 不变（`test_default_off_is_byte_for_byte_baseline` + 全量 1403 passed，唯一失败为预存 FeatureStore pandas3.14 超界，与 P1 无关）

**Acceptance**:
- 仓位绑定规则 opt-in 生效（高波动区间 vol-target < Kelly，低波动区间不绑定）✅
- MC 压力测试接入 CLI `--method stress`（诊断 method，不动 GO/NO-GO）✅
- 默认 off 时 4 策略回测 byte-for-byte 不变 ✅

**Deferred**：研究层大规模参数扫描优化（依赖 F8 vectorbt 裁决——「numpy 向量化并行」vs「重新评估 vectorbt 2026 兼容性」，用户 P1 启动前裁决）

**Done when**: `verification.json` + `review.json` passed

#### Phase 3: P2 AI 层升级（milestone-gate: P2-verify）

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
| 2. v0.1.3 发布候选准备 | 3. 发布证据与远端对齐 | In Progress | - |
| 3. deep-research 改进分批实施 | 1. P0 数据层防泄漏 | Planned | - |
| 3. deep-research 改进分批实施 | 2. P1 风控层补齐 | Planned | - |
| 3. deep-research 改进分批实施 | 3. P2 AI 层升级 | Planned | - |
