# Roadmap: QuantFlow 策略扩展与发布准备

## Overview

当前 roadmap 分为两个阶段：

- `M1` 已完成：4 个新增策略的实现与验证
- `M2` 进行中：`v0.1.3` 发布候选准备，目标是对齐版本、治理打包内容、重建制品校验信息，并为后续 tag / release 对齐铺平状态

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
