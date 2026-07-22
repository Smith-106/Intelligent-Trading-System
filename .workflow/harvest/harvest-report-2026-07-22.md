# Harvest Report — 2026-07-22

## Source

扫描所有 source registry 路径，30 天窗口（cutoff 2026-06-21）。发现 7 个 in-window session 未在 harvest-log 记录：

| # | Session | 类型 | 状态 |
|---|---------|------|------|
| 1 | 20260720-review-odyssey-p1-parity-paths | review-odyssey | COMPLETED, 30 findings, 17 fixed |
| 2 | 20260718-analyze-deepresearch-p0p1p2-macro | analysis (macro) | scope_verdict=large, GO_CONDITIONAL (88%) |
| 3 | 20260718-grill-deepresearch-implementation-plan | grill | 3 branches, context-package rich |
| 4 | 20260705-review-odyssey-security-fixes | review-odyssey | 14 fixed |
| 5 | 20260705-debug-odyssey-ci-ruff-breakage | debug-odyssey | COMPLETED |
| 6 | 20260705-security-audit-deep-quantflow-verify | security-audit-verify | verification matrix |
| 7 | 20260705-debug-odyssey-position-sizing-regression | debug-odyssey | END |

## Extraction Summary

- Fragments surveyed: ~25 candidate knowledge items across 7 sessions
- Fragments after dedup: 5 routed + 6 SKIP-DUP = 11 logged
- Duplicates skipped: 6（已通过 odyssey S_RECORD 或前次 harvest 落 spec/issue）

## Routing Results

### Spec (2 entries created)

| # | sid | 文件 | 标题 | 来源 | 关系 |
|---|-----|------|------|------|------|
| 1 | S-20260722-z4dr | review-standards.md | CCXT 交易所统一参数用 camelCase — verify against canonical docs not Python convention | p1-parity-paths-20260720 (SEC inline lesson) | independent |
| 2 | S-20260722-pd2y | architecture-constraints.md | backtest 不在 parity 范围 — parity 仅约束 paper/live 路径 | deep-research-20260718 (insight F7) | independent |

### Issue (3 entries created)

| # | ID | Severity | 标题 | 来源 |
|---|----|----------|------|------|
| 1 | ISS-20260722-001 | medium | F8 vectorbt spec 与 backtest.py 移除决策矛盾 — 待 conflict 审计裁决 | deep-research-20260718 REC-004 + grill |
| 2 | ISS-20260722-002 | high | P0 F1: MTF aligner open-time 跨 HTF 边界未收盘 bar 数据泄漏 — aligner 层只 ffill 已收盘 HTF bar | deep-research-20260718 REC-001 |
| 3 | ISS-20260722-003 | medium | P2: 新建 schema_exposure.py + RDAgentRunner.discover_factors 改签名接收 SchemaInfo | deep-research-20260718 REC-003 |

### Wiki (0 entries)

本批无 wiki-class 知识（findings/observations 已通过 spec/issue 落地，无需重复进 wiki 图）。

## Skipped (SKIP-DUP — already persisted)

| Fragment | 原因 |
|----------|------|
| compound strategy_id exact-key dict lookup | 已 spec S-20260720-98vs（odyssey S_RECORD 落盘） |
| ruff auto-commit lint-before-commit gate | 已 spec coding-conventions.md:80 + maestro overlay |
| pandas/numpy scalar == True E712 unsafe autofix | 已 spec debug-notes.md:29 |
| YAML key without matching model field silently dropped | 已 spec debug-notes.md:40 |
| REC-002 P1 vol-target/CVaR gate | 已 issue ISS-20260719-001 覆盖 |
| vectorbt run_combs 参数扫描 | 已 spec S-20260718-sffn（现因 ISS-20260722-001 进入 conflict 待裁决） |

## Conflict Routing (invariant 5)

ISS-20260722-001 标记 F8 vectorbt 为 genuine dispute（spec S-20260718-sffn ↔ backtest.py 移除决策矛盾）。建议后续执行 `maestro spec conflict mark .workflow/specs/coding-conventions.md <S-20260718-sffn 行> --note "F8 vectorbt 迁移方向与 backtest.py 故意移除矛盾，ISS-20260722-001 待审计裁决"`，由 `/manage-knowledge-audit` 解决。

## Provenance

所有 11 条记录已写入 `.workflow/harvest/harvest-log.jsonl`（5 routed + 6 skip-dup），每条含 fragment_id、source_type、source_id、routed_to、target_id、timestamp、confidence。

## No source artifacts modified

仅写入 `.workflow/specs/`、`.workflow/issues/issues.jsonl`、`.workflow/harvest/`。源码、session 文件、source artifact 均未修改。
