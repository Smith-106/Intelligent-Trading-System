# Harvest Report — 2026-07-20

## Source
- Type: brainstorm
- ID: 20260602-brainstorm-new-strategies
- Path: .workflow/scratch/20260602-brainstorm-new-strategies/brainstorm-output.md
- Updated: 2026-06-02（超出 --recent 30 默认窗口，经用户确认放宽收割——从未入库，知识游离风险）

## Extraction Summary
- Fragments found: 7（5 策略候选 + 1 实施顺序 + 1 架构兼容性）
- Filtered by dedup: 5 去重（见 Skipped）
- Duplicates skipped: 2
- Routed: 2

## Routing Results

### Wiki (1 entry)
| # | Type | Slug | Title | Status |
|---|------|------|-------|--------|
| 1 | knowhow | strategy-matrix-complementarity-and-rationale | QuantFlow 策略矩阵与互补性 + 候选学术依据 | CREATED |

> 5 个策略候选（HRV-01~05）中 4 个已实现（momentum_rotation/volatility_breakout/funding_rate/ml_ensemble 模板已存在），收敛为 1 个 knowhow 条目，记录代码注释未覆盖的增量：策略间互补性矩阵 + 学术依据。

### Spec (1 entry)
| # | Type | Content (truncated) | SID | Status |
|---|------|---------------------|-----|--------|
| 1 | arch | 跨交易所套利策略候选（P5，未实现）——市场中性统计套利，价差Z-Score/Half-Life/Hedge Ratio，Avellaneda & Lee (2010)... | S-20260720-5v13 | ADDED |

> 唯一未落地的策略候选，保留为 spec decision 候选。与现有 arch spec「新增策略实施顺序」（line 62-65）独立补充关系——现有记顺序，新条目记候选设计依据。

## Skipped
| Fragment | Reason |
|----------|--------|
| HRV-06 实施顺序 P1-P5 | [SKIP-DUP] architecture-constraints.md line 62-65 已有「新增策略实施顺序」spec-entry（date 2026-06-13） |
| HRV-07 架构兼容性（继承 StrategyBase + YAML） | [SKIP-DUP] CLAUDE.md 扩展指南已记录项目级约定，repo 已记录知识不重复收割 |

## Notes
- 收割时发现 5 个策略候选中 4 个已实现，brainstorm 的 P1-P4 顺序决策已落地为代码模板；P5 跨交易所套利仍未实现（架构改动大）。
- 此 artifact mtime 2026-06-02 超 30 天窗口，但 harvest-log 显示从未被收割，且含未入库的策略互补性/学术依据增量知识——经用户确认放宽窗口收割，避免知识丢失。
