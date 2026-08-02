# Project: QuantFlow

## What This Is

面向个人/小团队的 Crypto 量化交易系统（OKX），覆盖策略研究 -> 回测验证 -> 模拟盘 -> 实盘的完整闭环，内置防过拟合验证体系和六层模块化架构。

## Core Value

把“研究代码”推进到“可运行、可验证、可部署”的交易系统：

- 回测结果可通过 `CPCV + DSR + PBO + WFO` 交叉验证
- 风控链路完整，含 `Half-Kelly + VaR/CVaR + 回撤熔断 + Kill Switch`
- 策略扩展通过 `StrategyBase + YAML` 统一约束
- v0.2.0 发布：17 ISS 清零（安全加固 + 架构清理 + 新功能），tag `v0.2.0`（2026-08-02）

## Requirements

### Validated

- [x] L1 数据层：CCXT 获取 / 清洗 / Parquet + DuckDB / FeatureStore / Redis
- [x] L2 指标层：21 因子 / 注册表 / 趋势 / 动量 / 波动 / 成交量
- [x] L3 研究层：回测 / 优化 / 报告生成
- [x] L3 验证层：CPCV / DSR / PBO / WFO / GO-NO-GO
- [x] L4 信号风控：信号生成 / 风控引擎 / 仓位 / 风险指标 / 组合
- [x] L5 执行层：OKX / Paper / 执行引擎 / 订单 / 持仓 / KillSwitch
- [x] L6 监控层：Prometheus 指标 / 告警 / 日志
- [x] CLI 入口：Typer + Rich

### Active

- [x] P1 波动率突破策略（VolatilityBreakoutStrategy）
- [x] P2 资金费率策略（FundingRateStrategy）
- [x] P3 动量轮动策略（MomentumRotationStrategy）
- [x] P4 ML 集成策略（MLEnsembleStrategy）

### Out of Scope

- 新 Gateway 实现（如 A 股 miniQMT）- 当前聚焦 OKX
- 新数据源接入 - 当前 CCXT + OKX 已满足主链路
- Web UI / 前端页面 - QuantFlow Station 已上线（21 API 路由，9 功能组），处于活跃增强中
- 部署拓扑重构 - 当前 Docker Compose 已可支撑

## Current Version

**v0.2.0**（2026-08-02，tag `v0.2.0`，commit `fe43aeb`）

主要交付：
- 17 ISS 清零（安全加固：rate-limit/SSRF/redaction/Docker hardening/session security/CI hygiene）
- 架构清理：ExecutionEngine SRP 抽取 OrderRouter、ScalingPositionSizer 死代码删除、L6 Protocol 扩展、三账本 reconcile
- 新功能：IndicatorComputer Protocol 注入、recursive analysis CLI、benchmark service 抽取、structlog stdlib 桥接
- 多 Symbol 扩展基础设施部分落地（strategy/factory.py、per-symbol 实例化支持）
- **新增模块**：
  - `common/tracing.py` — 分布式追踪基础（correlation ID 传播 + OpenTelemetry 集成 + structlog processor）
  - `data/dq_monitor.py` — 实时数据质量监控（新鲜度/价格连续性/成交量异常检测 + Prometheus 指标）
  - `reconciliation/` — 仓位/订单漂移检测与对账引擎（HMAC 签名审计日志 + 后台对账循环）

## Context

当前系统已完成六层分层架构落地，且策略库已从基础的 `trend_following / mean_reversion` 扩展到：

- `elliott_wave`
- `volatility_breakout`
- `funding_rate`
- `momentum_rotation`
- `ml_ensemble`

所有新增策略均已接入：

- `research`
- `optimize`
- `validate`
- CLI 帮助与基础测试

## Constraints

- **API 安全**：API Key 只从环境变量读取，不写入代码或日志
- **实盘安全**：实盘模式必须启用 Kill Switch
- **数据格式**：Parquet Hive 分区 + DuckDB 零导入查询
- **特征一致性**：Feature Store 保证研究 / 实盘一致
- **测试要求**：核心模块测试覆盖率 > 70%

## Tech Stack

- **Language**：Python 3.11+（Docker 运行 `python:3.12-slim`；ruff/mypy target py311，`mypy --strict`）
- **Framework**：CCXT（OKX REST+WebSocket，async）、Optuna、自建纯 pandas/numpy 回测引擎（`BacktestEngine`，已替代 VectorBT — Py3.14+ numba 不兼容）
- **Data**：DuckDB + Parquet（Hive 分区 symbol/year/month）+ Redis（实时缓存）
- **Indicators**：27 注册因子（21 基础 + 6 Elliott Wave）via `FactorBase`/`IndicatorEngine`，纯 pandas/numpy（TA-Lib 可选）
- **Web**：aiohttp（QuantFlow Station，21 REST endpoints）+ Typer/Rich CLI（9 commands）
- **Config/Validation**：Pydantic v2（`AppConfig`）+ PyYAML；安全固定 `aiohttp>=3.14.1` / `cryptography>=48.0.1`
- **Monitoring**：Prometheus + Grafana + structlog；告警 Telegram/LINE；分布式追踪（correlation ID + OpenTelemetry 可选）
- **Data Quality**：实时数据质量监控（DataQualityMonitor，新鲜度/价格连续性/成交量异常，Prometheus 指标）
- **Reconciliation**：仓位/订单漂移检测（ReconciliationEngine + HMAC 审计日志）
- **AI**：`AIFactorEngine` + Meta-Labeling（已导出但未接线到管线）；`MLEnsembleStrategy` 使用自身内部 triple-barrier meta-labeling；FinBERT 情绪（`SentimentAnalyzer`/`NewsCollector` 已实现+测试，未导出/未接 CLI）；Qlib RD-Agent（**未实现**，规划中 E13-S1，qlib 为可选 `[ml]` extra）
- **Quality**：ruff format+lint、mypy strict、pytest+pytest-asyncio（coverage 70%）、pip-audit、pre-commit
- **Deployment**：Docker Compose（quantflow + redis + prometheus + grafana）

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| 自建事件驱动引擎 `TradingSession` | 避免额外引擎耦合，统一 backtest / paper / live | 已落地 |
| 防过拟合体系 `CPCV + DSR + PBO + WFO` | 防止回测结果失真 | 已落地 |
| `StrategyBase + YAML` 扩展策略 | 新策略最小侵入、统一接线 | 已验证 |
| 新策略复用既有 research / validate / CLI 管道 | 减少重复接线和维护成本 | 已完成 |

## Stakeholders

- 个人量化交易开发者（主用户）

---
*Last updated: 2026-08-02 after v0.2.0 release + new modules indexed (tracing, dq_monitor, reconciliation)*
