---
title: QuantFlow Project
related:
  - knowhow-doc-knowledge-hub
  - roadmap-roadmap
  - spec:project:architecture-constraints
---
# Project: QuantFlow

## What This Is

面向个人/小团队的 Crypto 量化交易系统（OKX），覆盖策略研究 -> 回测验证 -> 模拟盘 -> 实盘的完整闭环，内置防过拟合验证体系和六层模块化架构。

## Core Value

把“研究代码”推进到“可运行、可验证、可部署”的交易系统：

- 回测结果可通过 `CPCV + DSR + PBO + WFO` 交叉验证
- 风控链路完整，含 `Half-Kelly + VaR/CVaR + 回撤熔断 + Kill Switch`
- 策略扩展通过 `StrategyBase + YAML` 统一约束
- v0.5.0 当前：共享账本 symbol-level risk parity + 多 symbol paper 研究闭环；验收默认 **paper / paper_replay**（非交易 live）
- 历史：v0.2.0（17 ISS 清零 + 多 symbol 基建，tag `v0.2.0`，2026-08-02）；v0.4.0（checkpoint / 交易所熔断 / funding-OI）

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

**v0.5.0**（2026-08-08，代码 `quantflow.__version__`；相对 tag `v0.4.0` 超前研究/组合提交）

主要交付（相对 v0.2 累计）：
- **v0.5**：共享账本 multi-symbol + symbol-level risk parity 再平衡 + WFO OOS（`scripts/wfo_shared_rp.py` / `multi_symbol_replay.py`）
- **v0.4**：StateStore 崩溃恢复、ExchangeHealthMonitor、funding/OI 多源、对账生产接线
- **v0.2–0.3**：17 ISS 清零、多 symbol 基建、对账层、DQ monitor、Station 前端、tracing
- **验收口径（paper-first）**：策略/组合晋级与回归默认走 `quantflow run --mode paper` 与 paper_replay；交易权限 live 不在默认验收路径
- **开放研究**：生产候选 alpha 仍未过 WFO 生产门槛；RD-Agent 真管道（ISS-006）在途

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
- **AI**：`AIFactorEngine` + Meta-Labeling；`MLEnsembleStrategy` 内部 triple-barrier；FinBERT/情绪路径已测；`RDAgentRunner` + `quantflow ai {rdagent,research,train,register}` 半管道（发现→train 接线与 paper 注册加固见 ISS-006）；qlib 为可选 `[ml]` extra
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
*Last updated: 2026-08-08 — current version v0.5.0; paper-first acceptance; ISS-004/005 resolved*
