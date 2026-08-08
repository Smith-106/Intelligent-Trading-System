---
title: QuantFlow vs 前沿量化平台六维度差距分级总览（2026-08 对标）
category: finding
createdBy: harvest
sourceRef: 20260803-001-analyze
related:
  - session-run-maestro-benchmark-evolve-20260803-20260803-045922-20260803-001-analyze
type: knowhow
status: active
---
# QuantFlow vs 前沿量化平台六维度差距分级总览（2026-08 对标）

**Source**: 20260803-001-analyze（findings.json dimensions[]/gap_grading[]）
**Tags**: benchmark, architecture, gap-analysis

对标 NautilusTrader / QuantConnect LEAN / Qlib+RD-Agent / Freqtrade / VectorBT PRO / 幻方式 AI 范式（外部侧以用户调研材料为唯一事实源，二手信息未独立核验）：

| 维度 | 分级 | 要点 |
|------|------|------|
| 执行引擎 | 落后（一致性架构持平） | TradingSession 统一三模式方向正确；纯 Python 无 Rust/C++ 核心性能数量级落后；parity best-effort（regime gate 双路、PaperGateway 忽略 order.params）；OrderStatus 8 态完备但 partial-fill ws 增量未全接线 |
| AI 因子与模型研究 | 落后 | sklearn 基线（Meta-Labeling/GradientBoosting）可用；rd_agent.py 自认 integration skeleton，无 LLM 因子挖掘、无 CLI research 接线 |
| 数据地基 | 持平偏落后 | Parquet+DuckDB+FeatureStore PIT 防护完备；但仅 CCXT/OKX 单源 OHLCV，费率/OI/订单簿/链上全缺 |
| 风控体系 | 持平偏领先（单项缺失） | 7 层 fail-closed 检查+回撤熔断+CPCV/DSR/WFO 验证；交易所风险隔离缺失、对账引擎未生产装配 |
| 监控运维 | 持平（故障恢复落后） | Prometheus/Grafana/告警完备；无持仓/订单状态持久化与崩溃恢复（无 checkpoint/WAL 证据） |
| 加密特色能力 | 大部分缺失 | FundingRateStrategy 仅方向性策略壳且喂数断链（update_funding_rate 全库零调用方）；订单簿/链上/跨所套利全缺 |

总体判断：架构骨架与 fail-closed 安全姿态是可比资产，执行性能/AI 研究/数据广度是负债。配套路线图见 note harvest-roadmap-dag 条目。
