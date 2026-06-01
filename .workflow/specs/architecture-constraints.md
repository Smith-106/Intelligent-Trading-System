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
  - quantflow/execution/ — 网关、执行引擎、订单管理 (L5)
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
- execution → common + monitoring.metrics
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
