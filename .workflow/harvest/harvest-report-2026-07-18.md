# Harvest Report — 2026-07-18

## Source
- Type: research (external deep-research workflow output)
- ID: deep-research-20260718
- Path: 临时输出文件 + deep-research workflow task `w872shegz`
- Origin: 108-agent deep-research harness (5 search angles, 26 sources fetched, 124 claims → 25 verified, 24 confirmed / 1 refuted)

## Extraction Summary
- Fragments found: 15 (from 15 verified findings + refuted-claim context)
- Filtered by confidence: 0 (all ≥ 0.5)
- Duplicates skipped: 0 (no overlap with existing harvest-log or stores after dedup check)

## Routing Results

### Issue (5 entries)
| # | Severity | ID | Title | Status |
|---|----------|----|-------|--------|
| 1 | high | ISS-20260718-001 | MTF 对齐 reindex+ffill 缺 shift(1)，潜在 0.20 ROC-AUC look-ahead 虚高 | CREATED |
| 2 | high | ISS-20260718-002 | 缺自动化 look-ahead/递归公式检测 CLI（Freqtrade 等价物） | CREATED |
| 3 | medium | ISS-20260718-003 | PositionSizer 缺 vol-targeting，应绑定 min(half-Kelly, vol-target, 单名上限) | CREATED |
| 4 | medium | ISS-20260718-004 | parametric-normal VaR 低估 crypto 肥尾，ES_97.5 应提为主指标 | CREATED |
| 5 | medium | ISS-20260718-005 | 验证栈缺 Monte Carlo 压力测试层（Jesse 等价物） | CREATED |

### Spec (4 entries)
| # | Category | SID | Title | Status |
|---|----------|-----|-------|--------|
| 6 | arch | S-20260718-cxia | LLM 因子挖掘须采纳 schema-only 数据中心设计防泄漏 | ADDED |
| 7 | arch | S-20260718-h6ml | 回测-实盘 parity 范式：同语义执行+同确定性时钟 | ADDED |
| 8 | coding | S-20260718-sffn | 研究层大规模参数扫描用 vectorbt run_combs/Portfolio.from_signals 多资产 broadcasting | ADDED |
| 9 | review | S-20260718-c3vv | 仓位绑定规则取三者下界 + ES_97.5 主风险指标 + fat-tail 警示 | ADDED |

### Wiki (6 entries)
| # | Slug | Title | Status |
|---|------|-------|--------|
| 10 | DOC-knowhow-rdagent-q-factor-mining-architecture | RD-Agent(Q) 五单元闭环 + Co-STEER DAG + bandit 调度因子挖掘架构 | CREATED |
| 11 | DOC-knowhow-fingpt-v33-finbert-upgrade | FinBERT→FinGPT v3.3 升级路径（单卡 RTX 3090/$17.25） | CREATED |
| 12 | DOC-knowhow-sentiment-dissemination-breadth | 情绪分析传播广度感知（聚类+prompt 注入，+8 个百分点） | CREATED |
| 13 | DOC-knowhow-qlib-model-zoo-benchmark | Qlib 20+ SOTA 模型动物园可作因子/模型基准 | CREATED |
| 14 | DOC-knowhow-data-layer-upgrade-polars-clickhouse | 数据层升级候选:Polars+ClickHouse/QuestDB;DuckDB QUALIFY ROW_NUMBER 实现 PIT 特征存储 | CREATED |
| 15 | DOC-knowhow-live-cost-modeling-funding-fee-alerts | 实盘成本建模:滑点+手续费腰斩收益;永续 funding fee 不可忽略;Grafana 告警检测用户面症状 | CREATED |

## Skipped
None.

## Caveats & Confidence Tiers

| Finding | Confidence | Vote | Caveat |
|---------|-----------|------|--------|
| F1 MTF ffill look-ahead | high | 3-0 | 严重程度取决于 fetcher 时间戳语义(bar-open vs bar-close)，未验证 |
| F2 look-ahead 检测 CLI | high | 3-0 | — |
| F3 vol-targeting 缺失 | high | 3-0 | 具体阈值(10%/40%/3x) claim 已 0-3 否决，仅 vol-target 机制成立 |
| F4 parametric VaR 肥尾 | high | 3-0 | — |
| F5 Monte Carlo 缺失 | high | 3-0 | — |
| F6 RD-Agent schema-only | high | 3-0 | — |
| F7 回测-实盘 parity | high | 3-0 | Backtrader 停止维护，仅作范式参照 |
| F8 vectorbt 参数扫描 | high | 3-0 | 需核实研究层是否已用 run_combs |
| F9 仓位绑定+ES 主指标 | high | 3-0 | 阈值 claim 已否决，机制成立 |
| F10 RD-Agent 架构 | high | 3-0 | 2× ARR 基准 medium |
| F11 FinGPT 升级 | medium-high | 2-1 | beat GPT-4 为自报，2023 基准非最新 |
| F12 传播广度 | high | 3-0 | N=380 小样本 workshop，周度方向预测非点位 |
| F13 Qlib 模型 zoo | high | 3-0 | — |
| F14 数据层升级 | medium | fetch-only | 未单独对抗验证 |
| F15 实盘成本建模 | medium | fetch-only | 未单独对抗验证 |

## Refuted Claims (excluded from routing)
| Claim | Vote | Source | Reason |
|-------|------|--------|--------|
| 10% 单名上限/40% top-3 集中度/gross 杠杆 >3× 无止损触发 flag | 0-3 | Viprasol-Tech/risk-management-review | 来源自相矛盾(同时声称 10% 上限和 >15% 红旗)+0 star 单次提交+自我声明教育用途非安全保证，非权威/同行评议标准 |

## Relationship Classification (vs existing specs)
- F6/F7 (arch) vs existing `architecture-constraints.md` MTF/parity 条目 → **independent** (主题不同：现有讲 generate_signals 双模式，新条目讲 LLM 隔离与 parity 范式参照)
- F8 (coding) vs existing look-ahead 条目 → **independent** (现有讲 entries mask 聚合泄漏，新条目讲 vectorbt 参数扫描利用)
- F9 (review) → 无现有匹配，全新
- 无 supersede 或 conflict 关系

## Next-step Routing
- 查看 issues: `maestro delegate` 或 `Skill({ skill: "manage-issue", args: "list --source harvest" })`，5 条新增（ISS-20260718-001~005）
- 查看 specs: `maestro load --type spec --keyword vol-target` / `--keyword schema-only`
- 查看 wiki: `maestro wiki list --type knowhow --tags ai`
- 连接 wiki 图: `Skill({ skill: "wiki-connect", args: "--fix" })`
- 审计 spec 冲突: `/manage-knowledge-audit --scope spec`
- 实施优先级: F1/F2 为 P0（代码级风险），F3/F4/F5 为 P1，AI 层 F10/F11/F12 为 P2
