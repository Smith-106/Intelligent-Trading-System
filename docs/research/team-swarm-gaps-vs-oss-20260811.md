# Best Solution — Team Swarm: QuantFlow residual gaps vs OSS

**Session**: `20260811-team-swarm-gaps`  
**Run**: `20260811-001-team-swarm`  
**Converged**: max_iterations=3  
**Best ant**: **ANT-2-3** (verified_score ≈ **0.407**)  
**Reference**: `Desktop/oss-quant-benchmark` + prior architecture diagnosis  

---

## Elite path (ACO best)

```text
N_no_engine_rewrite
  → N_ops_t023_t024_calendar
  → N_meta_funding_oi_density
  → N_orderbook_paper_fidelity
  → N_multi_symbol_book_risk
```

**含义**：不换引擎 → **日历运营 T023/T024** → **funding/OI 密历史（新合同）** → **paper BBO 真正喂入会话** → **可选开启多标的 book risk（仅 paper）**。

### Runner-up paths

| Rank | Ant | Path (summary) | Score |
|------|-----|----------------|-------|
| 1 | ANT-2-3 | no-rewrite → T023 → meta → BBO → book risk | 0.407 |
| 2 | ANT-1-4 | no-rewrite → T023 → meta → BBO → MC significance | 0.383 |
| 3 | ANT-3-4 | meta → T023 → PIT → anti-overfit → no-rewrite | 0.365 |
| 4 | ANT-2-1 | no-promote → T023 → fingerprint CI → meta → parity | 0.361 |
| 5 | ANT-3-1 | BBO → T023 → latency TCA → parity → no-rewrite | 0.317 |

---

## 不足清单（相对 OSS，按优先级）

| 优先级 | 不足 | OSS 参照 | QuantFlow 现状 | 建议动作 |
|--------|------|----------|----------------|----------|
| **P0** | **纸面日课样本不足** | freqtrade dry-run 连续运行文化 | T023 **4/7**；T024 等 ≥7 + fills≥20 | **人跑日课**（非代码 wave） |
| **P1** | **funding/OI 历史密度** | jesse/freqtrade 市场数据面 | FeatureStore 可 as-of join；B3 曾因稀疏 0 成交 | 回填 meta parquet；**新合同 ID**，不改 B3–B5 冻结 |
| **P1** | **paper 盘口保真未串会话** | hummingbot sim fill / nautilus order book | `orderbook_fill` + IMP-09 配方已有；会话少调 `update_orderbook` | `paper_day_session` 可选 BBO poll |
| **P1** | **晋级指纹 CI 覆盖面** | jesse 不把 hyperopt 当晋级 | IMP-01 attach + 静态锁已有 | 扩 fixture 断言 research JSON `promotion_eligible=false` |
| **P2** | **MC/显著性默认附着** | jesse bootstrap / freqtrade lookahead-analysis | `monte_carlo.py` 存在；dual-path 默认不挂 | dual_path 可选 attach MC stress |
| **P2** | **RD-Agent 离线作业深度** | qlib `qrun` workflow | 模块+IMP-07 配方；默认 `rd_agent.enabled=false` | 一次性 offline job 脚本 → `ai_reports/` only |
| **P2** | **多标的 book risk 默认关** | vnpy/lean 组合层 | PortfolioManager/RiskParity 在位 | paper smoke 配置；live 仍关 |
| **P3** | **Jesse DX 完整度** | jesse 海量 strategy fixtures | SimpleStrategy + scaffold；IMP-08 partial | `new-strategy` CLI + examples |

## 明确「不是不足」/ 不要学坏

| 项 | 结论 |
|----|------|
| 六层架构 vs Nautilus/Lean | **不重写** — B0 PAPER-GO 已证研究 OS 可用 |
| 多交易所超市 / HFT MM | **非目标** |
| Hyperopt 当晋级 | **禁止**（freqtrade 能力 ≠ QF 晋级路径） |
| Path A+B combined_score | **禁止** |
| 松 fee/funding 抬胜率 | **禁止** |
| 改 B0/B3–B5 冻结参数 | **禁止** |

## 与已落地 IMP 的关系

| 已落地 | Swarm 立场 |
|--------|------------|
| IMP-01…05 接线/PIT/multi-symbol/ops | **保留** |
| IMP-06 hard_bind 锁 | **保留** |
| IMP-07/09 配方文档 | **保留**；残余是 **作业/会话接线** |
| Path B OOS 6 窗 + 成本附件 | **大多完成**；残余 MC 附着可选 |
| 性能面板 re-verify | 系统指标健康；短板在 **运营与 meta 数据** |

## 建议下一刀（执行顺序）

```text
1) [人] T023 日课至 7/7  → T024 evidence dry-run
2) [码] funding/OI 回填脚本 + 新合同（不改冻结）
3) [码] paper_day_session --orderbook-fill + BBO poll
4) [码] dual_path 可选 monte_carlo attachment
5) [码] research JSON promotion_eligible CI fixtures
6) [可选] RD-Agent offline job / multi-symbol book risk paper smoke / IMP-08 DX
```

## 一句话

> **QuantFlow 相对 OSS 的短板不在“换引擎”，而在：纸面样本墙钟、meta 数据密度、paper 盘口会话接线，以及可选的显著性/AI 离线作业深度；晋级与冻结纪律应继续 fail-closed。**
