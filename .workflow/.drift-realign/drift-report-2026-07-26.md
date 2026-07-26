# Drift Realign Report — 2026-07-26

## Timeline Window
- From: 2026-07-15 → To: 2026-07-26 (11 days)
- Git: 90 commits, 172 files changed (+18711 / -2301)
- Sessions: 0 (wiki not indexed — W001, degraded to git-only timeline)
- Drift Score: **SEVERE** (≈216: 11d × √172 × 1.5 roadmap-weight)

## Scan Summary
- Total findings: **21** (4 P0 / 12 P1 / 5 P2)
- By scope: roadmap 8 / spec 1 / codebase 7 / issue 1 / state 2 / project 1 / knowhow 1
- Conflict-markers merged: 0 (no pre-existing conflict markers)

## Root Cause of Drift
roadmap.md (last commit `aa57923`, 2026-07-20) + codebase docs lagged behind a burst of 07-21~07-25 activity: P1-verify PASS (07-21) + Wave 1-5 multi-book reconcile (07-25) + v0.1.3 tag/release (existed since 06-07 but roadmap still said "未创建"). The 07-25 codebase-refresh updated tech-registry but left `_refresh_meta.removed_symbols` indexer artifacts and missed Wave 1-5 architectural descriptions.

## Actions Applied

| # | ID | Scope | Sev | Drift Type | Target | Action |
|---|----|----|----|----|--------|--------|
| 1 | DFT-1a3f7c02 | roadmap | P0 | stale_progress | M3 P1 status 待verify→PASS | update |
| 2 | DFT-2b8e1d47 | roadmap | P0 | stale_progress | M3 P2 blocked→unblocked | update |
| 3 | DFT-3c9f2e58 | roadmap | P0 | phantom_phase | Wave 1-5 未入册→新 Phase 4 | update |
| 4 | DFT-4d1a3b69 | roadmap | P0 | stale_progress | M2 v0.1.3 已发布→[x] | update |
| 5 | DFT-5e7c4f8a | roadmap | P1 | timeline_impossible | P0.3 baseline 失效注记 | update |
| 6 | DFT-6f8d5a9b | roadmap | P1 | outdated_criteria | Overview 反映 reconcile 契约 | update |
| 7 | DFT-7a9e6b0c | roadmap | P1 | outdated_criteria | CLAUDE.md Phase3✅ 注历史轴 | update |
| 8 | DFT-8b1f7c3d | state | P2 | stale_progress | current_task_id→M3-P2 | update |
| 9 | DFT-2f9a4c71 | spec | P1 | stale_dependency | arch L38 execution→Protocol注入 | update |
| 10 | DFT-7a3c9e01 | codebase | P1 | concern_drift | TC-007 removed_symbols 清空 | update |
| 11 | DFT-8b1f4c27 | codebase | P1 | concern_drift | TC-008 removed_symbols 清空 | update |
| 12 | DFT-9c2e5d83 | codebase | P1 | concern_drift | TC-009 removed_symbols 清空 | update |
| 13 | DFT-1d4a6f72 | codebase | P1 | feature_missing | portfolio realized_pnl+baseline | update |
| 14 | DFT-2e5b7a94 | codebase | P1 | architecture_outdated | PositionManager→薄路由 | update |
| 15 | DFT-3f6c8b15 | codebase | P1 | concern_drift | daily_loss total-vs-baseline | update |
| 16 | DFT-4a7d9e36 | codebase | P2 | feature_missing | POSITION_EPSILON 入 symbols | update |
| 17 | DFT-0a3f1c9b | issue | P1 | issue_stale_open | ISS-20260723-001→resolved | archive |
| 18 | DFT-1b7c2e0a | state | P2 | deferred_resolved | 2 stale tag blockers 移除 | update |
| 19 | DFT-2c8d4f1e | project | P1 | project_tech_drift | research_engine default→eventdriven | update |
| 20 | DFT-3d9e5a2f | knowhow | P2 | knowhow_code_ref_dead | 加 not-implemented frontmatter | keep |
| 21 | DFT-4e1f6b3c | state | P2 | orphan_session | 核查: 无真实 orphan, sessions 已当前 | keep |

## Action Counts
- update: 18 (含 1 issue archive + 1 codebase doc-index 修 + roadmap 重写 + spec 修正 + state 清理)
- archive: 1 (ISS-20260723-001 resolved)
- keep: 2 (knowhow frontmatter 加注 + orphan_session 核查无实际 orphan)
- rebuild: 0 (codebase P0 = 0, 不触发 /quality-sync --full; codebase 漂移是 indexer 元数据 + 描述, 已直接修)

## Auto-Rebuilt
- /quality-sync --full triggered: **no** (codebase scope P0 < 3; only P1 indexer/description drift, fixed directly)
- /manage-codebase-rebuild suggested: no (tech-registry structure intact, only content patches needed)

## Verification
- `python -m ruff check quantflow/common/config.py` → All checks passed
- `pytest tests/unit/test_config.py::TestConfigSchemaDrift` → 1 passed (research_engine default.yaml key now matches pydantic field, no dropped key)
- `from quantflow.common.config import StrategyConfig` → `research_engine: eventdriven` ✓

## Backup
- Location: `.workflow/.trash/drift-realign-20260726T103000/`
- 10 files backed up (roadmap.md, state.json, arch-constraints.md, doc-index.json, signal-risk-layer.md, execution-layer.md, issues.jsonl, CLAUDE.md, default.yaml, config.py)

## Residual / Follow-up
1. **ISS-20260723-002~012 逐条核查** — artifact-scanner 建议同类 deferred issue 需确认 odyssey-improve/review 批次（4d3efb3 关 6 / ce5ce98 关 20）覆盖情况，本次未全量核查（超出 drift-realign 范围）
2. **research_engine schema-drift 深修** — 字段零消费方（specs/learnings YAML-schema-drift 模式），本次仅修 default 消除「永不工作」漂移；真正修复需新增消费逻辑或删字段（feature work，非 drift-realign）
3. **P0.3 byte-for-byte 回归守卫重立** — Wave 1-5 重写 engine，基线需对当前 HEAD 重立（roadmap 已注记）
4. **.workflow/sessions/ 目录** untracked 状态 — git 未跟踪，建议 `git add` 或加入 .gitignore 明确归属
