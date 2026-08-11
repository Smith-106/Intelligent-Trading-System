# Research docs index (north star)

**North star**: cost-aware paper-first research OS — not win-rate.  
**Release**: v0.7.1 · **Wave track**: closed (W27); no auto W28.

## Start here

| Doc | Why |
|-----|-----|
| [pending-checklist.md](./pending-checklist.md) | **唯一待办权威**：P0=T023/T024 运营 |
| [improvement-plan-20260811.md](./improvement-plan-20260811.md) | 完善计划 Wave A–D（执行边界） |
| [Candidate-Baseline-6-meta.md](./Candidate-Baseline-6-meta.md) | B6-META 数据密度合同草案 |
| [team-swarm-gaps-vs-oss-20260811.md](./team-swarm-gaps-vs-oss-20260811.md) | OSS 对照残差（swarm） |
| [performance-metrics-verify-20260811.md](./performance-metrics-verify-20260811.md) | 组合/overlay/PathB 性能面板 |
| [market-capability-verify-20260811.md](./market-capability-verify-20260811.md) | 研究栈能力冒烟 |
| [dual-path-research-os-20260811.md](./dual-path-research-os-20260811.md) | 双路径 OS 设计 |
| [oss-adversarial-improvement-plan-20260811.md](./oss-adversarial-improvement-plan-20260811.md) | IMP-01…05 landed · 06–09 optional |
| [btc-dd-return-optimize-20260811.md](./btc-dd-return-optimize-20260811.md) | Path A primary **w=0.30** |
| [Candidate-Baseline-0.md](./Candidate-Baseline-0.md) · [Candidate-Baseline-0-results.md](./Candidate-Baseline-0-results.md) | B0 合同与 PAPER-GO 结果 |
| [how-to-close-p0-p3.md](./how-to-close-p0-p3.md) | 日课→T024 操作手册 |
| [t023-wall-clock-status.md](./t023-wall-clock-status.md) | streak 墙钟 |

## Path map

```text
paper_replay  ── multi_symbol_replay / B0 ──► PAPER-GO candidate (ops T023/T024)
vectorized    ── dual-path / overlay / path_b_oos ──► research only (no promote)
live          ── needs human + sample floors ──► default OFF
```

## Frozen contracts (do not silently edit)

- B0 / B3 / B4 / B5 KEEP  
- No `combined_score`  
- IAF `hard_bind_entry=false`  
- Research `promotion_eligible=false` until paper path  

## Learnings distill

Workflow knowhow: `.workflow/knowhow/DOC-20260811-learnings-params-structure.md`  
(also linked from Knowledge Hub after promote/sync)

## Ops recipes (optional polish)

| Doc | IMP |
|-----|-----|
| [paper-orderbook-fill-recipe.md](../ops/paper-orderbook-fill-recipe.md) | IMP-09 |
| [rdagent-offline-job-recipe.md](../ops/rdagent-offline-job-recipe.md) | IMP-07 |

Research contract overlays (not catalog): `quantflow/config/research/overlays/`

