---
title: QuantFlow 演进路线图：三阶段四 session DAG（benchmark-evolve）
category: finding
createdBy: harvest
sourceRef: 20260803-002-roadmap
related:
  - session-run-maestro-benchmark-evolve-20260803-20260803-045922-20260803-002-roadmap
type: knowhow
status: active
---
# QuantFlow 演进路线图：三阶段四 session DAG（benchmark-evolve）

**Source**: 20260803-002-roadmap（roadmap.json，alias current-roadmap）
**Tags**: roadmap, planning, benchmark

面向 AI 原生量化的三阶段演进（机读产物：session maestro-benchmark-evolve-20260803-20260803-045922 run 20260803-002-roadmap/outputs/roadmap.json）：

- **P1 地基补强**：s1-integrity-foundation（对账生产装配/partial-fill 补全/崩溃恢复/交易所熔断/parity 收敛）∥ s2-multisource-data（费率/OI 采集 + FundingRateStrategy 接线）——两者无依赖并行（wave 1）
- **P2 AI 能力升级**：s3-ai-research-pipeline（RD-Agent 实装/多源特征/MLOps 晋级门），依赖 s1+s2（wave 2）
- **P3 策略工厂化**：s4-strategy-factory（多策略并行/动态风险预算/自动进化闭环），依赖 s3（wave 3）

关键决策：RD-0 接受中低频定位不追 Rust/C++ 重写（详见 spec S-BM2603-RD0）；RD-2 数据先行（多源数据同时阻塞加密特色与 AI 特征两条线）；RD-3 链上/跨所/订单簿 tick 延后至 P3 后候选。

不变量：尊重六层架构不破坏性重构；新增防线一律 fail-closed；TradingSession 单一真理源仅收敛 parity 细节。每 session 附可量化 success criteria；session 内任务拆分留给 plan。
