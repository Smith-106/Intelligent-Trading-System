# Harvest Report — 2026-08-03 (benchmark-evolve session)

## Source
- Type: analysis + roadmap（同 Session 前序 Runs）
- ID: 20260803-001-analyze, 20260803-002-roadmap
- Session: maestro-benchmark-evolve-20260803-20260803-045922
- Path: .workflow/sessions/maestro-benchmark-evolve-20260803-20260803-045922/runs/
- Mode: --auto（自动分类路由，非交互）

## Extraction Summary
- Fragments extracted: 27（analyze: 7 findings + 3 decisions + 7 risks + 4 open_questions = 21；roadmap: 4 decisions RD-0..3 + DAG/sessions + invariants = 6）
- Filtered by confidence (<0.5): 0
- Consolidated into routed items: 15（如 F1→W1、F2→RD-0 spec、F5→ISS-001、risks/open_questions 合并入对应 issue 与 wiki 条目）
- Routed: 12（wiki 5 + spec 1 + issue 6）
- Duplicates skipped: 0（dedup 核查 harvest-log.jsonl / issues.jsonl / specs / wiki：无同题命中）

## Routing Results

### Wiki (5 entries，type=knowhow via `maestro wiki create`)
| # | Category | Target ID | Title | Status |
|---|----------|-----------|-------|--------|
| 1 | finding | knowhow-doc-harvest-analysis-gap-grading | 六维度差距分级总览（2026-08 对标） | CREATED |
| 2 | finding | knowhow-doc-harvest-analysis-data-single-source | 数据单源是最大结构性短板（阻塞两条演进线） | CREATED |
| 3 | knowhow | knowhow-doc-harvest-analysis-highflyer-principles | 幻方式范式：借鉴生产方式原则而非硬件规模 | CREATED |
| 4 | knowhow | knowhow-doc-harvest-analysis-benchmark-methodology | 对标分析方法论：四级分级 + 外部事实源边界 | CREATED |
| 5 | finding | knowhow-doc-harvest-roadmap-evolution-dag | 三阶段四 session 演进路线图 DAG | CREATED |

### Spec (1 entry)
| # | Category | Target ID | Content | Status |
|---|----------|-----------|---------|--------|
| 1 | arch | S-BM2603-RD0 | QuantFlow 接受中低频定位，不追赶 Rust/C++ 执行核心（RD-0 决策 + 代价 + 不变量 + 信息边界） | ADDED（specs/architecture-constraints.md） |

### Issue (6 entries，追加至 issues/issues.jsonl)
| # | Severity | ID | Title | Roadmap 归属 |
|---|----------|----|-------|--------------|
| 1 | high | ISS-20260803-001 | FundingRateStrategy 生产路径喂数断链 | s2-multisource-data |
| 2 | high | ISS-20260803-002 | 对账引擎未接入生产运行时 | s1-integrity-foundation |
| 3 | high | ISS-20260803-003 | 交易所风险隔离缺失（无交易所级熔断/敞口上限） | s1-integrity-foundation |
| 4 | medium | ISS-20260803-004 | 进程崩溃后持仓/订单状态无持久化恢复 | s1-integrity-foundation |
| 5 | medium | ISS-20260803-005 | paper/live parity 收敛（partial-fill/regime gate/params） | s1-integrity-foundation |
| 6 | medium | ISS-20260803-006 | RD-Agent/qlib AI 研究管道实装 | s3-ai-research-pipeline |

## Skipped
| Fragment | Reason |
|----------|--------|
| （无） | dedup 检查通过，0 跳过 |

## Notes
- 写入前已备份：issues/.backups/issues.jsonl.backup-harvest-20260803-132500、harvest/harvest-log.jsonl.backup-20260803-132500
- 首轮追加因 PowerShell 5.1 默认 ANSI 解码损坏 UTF-8，已从备份恢复并以 -Encoding UTF8 重放，node JSON.parse 全量校验通过
- fail-closed 姿态、partial-fill 累计量契约等已在既有 spec/knowhow 中存在，未重复沉淀（consolidated 而非 routed）

```
=== HARVEST COMPLETE ===
Source: 20260803-001-analyze + 20260803-002-roadmap (session maestro-benchmark-evolve-20260803-20260803-045922)

  Wiki:  5 created, 0 skipped
  Spec:  1 added,   0 skipped
  Issue: 6 created, 0 skipped

  Report: .workflow/harvest/harvest-report-2026-08-03.md
  Log:    .workflow/harvest/harvest-log.jsonl

Next:
  → Review wiki entries: maestro wiki list --type knowhow
  → Triage issues: ISS-20260803-001..006（均已标注 roadmap session 归属）
  → View specs: S-BM2603-RD0 @ .workflow/specs/architecture-constraints.md
```
