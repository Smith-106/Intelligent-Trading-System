# v0.4.0 Release Notes — 2026-08-03

## 概述

Wave 1 (s1-integrity-foundation + s2-multisource-data) 实施完成：运营完整性基础 + 多源数据采集首期交付。

## 新功能

### Checkpoint 状态存储 (ISS-20260803-004)
- quantflow/execution/state_store.py：会话崩溃恢复持久化
- 原子写入（tmp + os.replace）+ schema 版本校验 + fail-closed 恢复

### 交易所健康监控 (ISS-20260803-003)
- quantflow/execution/exchange_health.py：单交易所熔断器
- 滑窗错误率 + OKX 50011 限频连续检测 + 滞后冷却恢复
- RiskEngine 单点拦截（exchange_circuit_open）

### 市场元数据采集 (ISS-20260803-001)
- quantflow/data/market_meta_fetcher.py：Funding Rate / Open Interest
- 自限频（>=200ms）+ 轮询地板 + 指数退避重试
- FundingRateStrategy 生产路径修复

### 会话恢复与对账接入 (ISS-20260803-002)
- TradingSession.start 恢复 Checkpoint 并经 ReconciliationEngine 验证
- 对账引擎正式接入生产运行时

## 测试

- 177 个测试通过（68 新单元 + 20 新集成 + 89 回归）
- 新增 paper/live parity 集成测试

## 知识收割

- benchmark-evolve session：5 wiki + 1 spec (S-BM2603-RD0) + 6 issues
- 决策：接受中低频定位，不追赶 Rust/C++ 执行核心

## 升级说明

- 无破坏性变更
- 新模块默认启用（fail-closed 语义）
- 配置：default.yaml 新增 exchange_health / market_meta 节
