# Drift Realign Report — 2026-07-28 (r2)

## Timeline Window
- From: 2026-07-28 → To: 2026-07-28 (1 day, c51d571..HEAD 5 commits)
- Git: 5 commits, 40 files changed (+1997 / -5689)
- Sessions: 0 (wiki 未索引, W001 — git-only timeline, [LOW CONFIDENCE])
- Drift Score: 9.49 (LOW; 1 × √40 × 1.5 max-scope-weight)
- Hot paths: .workflow/codebase/ (6), quantflow/web/ (6), data/station_history/ (5), .workflow/ (4), .workflow/specs/ (4), tests/unit/ (4)

## Scan Summary
- Total findings: 19 (0 P0 / 7 P1 / 12 P2)
- By scope: roadmap 2 / spec 5 / codebase 8 / artifact 4 / state 0 / knowhow 0 / project 0
- 4 scanner agents all returned (GATE 3 passed). Findings 源于 ISS-012 (8ffd612) + UX (4e32c24) + REG-1 (74b83d1) 三批 code commit 后的文档未同步 + 上轮 drift-realign 遗漏 (doc-index.json TC-005)。
- Conflict-marker 集成: `maestro spec conflict list` → No conflicts or degraded entries found (无重叠合并)。

## Triage Mode
- 用户裁决: 全部 update + 直接更新文档内容 (不注入 TODO 注释, evidence 充分含精确行号)
- P2 (12 条): 其中 2 条 roadmap (keep, 已加 post-verify 注记)、2 条 artifact (UX/REG-1 issue 登记, keep — 用户上次明确 UX 不建 issue, REG-1 是 knowhow 已在 tester wisdom)、1 条 spec console.status (keep, 次要工程化范式)、其余 7 条 P2 均随相关文件 update 一并处理。

## Actions Applied

| # | DFT ID | Scope | Severity | Drift Type | Target | Action |
|---|--------|-------|----------|-----------|--------|--------|
| 1 | DFT-7f3a2c1b | codebase | P1 | doc_index_stale | doc-index.json TC-005 (scaling_position_sizer.py + 4 Scaling 符号) | update |
| 2 | DFT-1a5c6d3e | codebase | P1 | feature_missing | signal-risk-layer.md (ISS-012 config-sourcing) + common-foundation.md | update |
| 3 | DFT-3c7e8f5a | codebase | P1 | feature_missing | web-station.md (UX M1-M5/H1/L2 + fonts/ + setHTML) | update |
| 4 | DFT-5e9a0b7c | codebase | P2 | doc_index_stale | doc-index.json last_updated (2026-07-25→2026-07-28) | update |
| 5 | DFT-8b4e1d9c | codebase | P2 | doc_index_stale | signal-risk-layer.md L31 (ScalingPosition 遗留) | update |
| 6 | DFT-9c2f4e0a | codebase | P2 | doc_index_stale | feature-maps/risk-controls.md L27 (ScalingPosition 遗留) | update |
| 7 | DFT-2b6d7e4f | codebase | P2 | doc_index_stale | cli-entry.md + feature-maps/cli.md (行号 stale +1~+167) | update |
| 8 | DFT-4d8f9a6b | codebase | P2 | feature_missing | cli-entry.md (REG-1 + UX H2/H3/H4) | update |
| 9 | DFT-7a9e6b0c | spec | P1 | feature_missing | coding-conventions.md (config-sourced baseline 范式) | update (maestro spec add) |
| 10 | DFT-3c8f1d2e | spec | P1 | feature_missing | architecture-constraints.md S-20260705-revk (web XSS choke-point 扩展) | update |
| 11 | DFT-9b2c4e71 | spec | P1 | feature_missing | coding-conventions.md (credential redaction + REG-1 fail-closed) | update (maestro spec add) |
| 12 | DFT-5e1a8f3d | spec | P2 | test_convention_gap | test-conventions.md (静态 guard + config schema drift guard 范式) | update |
| 13 | DFT-a7e6b0c1 | artifact | P2 | state_stale_timestamp | state.json last_drift_realign (2026-07-26→2026-07-28T21:00) | update (原子写) |
| 14 | DFT-2f4c8d1a | artifact | P2 | accumulated_stale | state.json key_decisions (+4 架构决策指针: MonitoringSink/OrderRouter/multi-book reconcile/ISS-012) | update (原子写) |
| 15 | DFT-9b2c1e7a | roadmap | P2 | missing_post_verify_fix_annotation | roadmap.md Phase 2 末尾 (ISS-012 post-verify 注记) | update |
| 16 | DFT-a3f0c5d1 | roadmap | P2 | untracked_workflow_not_on_roadmap | roadmap.md (UX 不在 M3 跟踪轴, Scope Decisions 说明) | keep (已并入 #15 注记) |
| 17 | DFT-2f9a4c71 | spec | P2 | feature_missing | coding-conventions.md (console.status CLI UX, 次要) | keep |
| 18 | DFT-3b7e1c25 | artifact | P2 | project_req_drift | issues.jsonl (UX 11 issues 未登记) | keep (用户明确 UX 不建 issue) |
| 19 | DFT-9d2a4f17 | artifact | P2 | deferred_resolved | issues.jsonl (REG-1 未登记) | keep (REG-1 root pattern 已在 tester wisdom) |

## Summary
- Updated: 16 (直改文档内容 + 2 maestro spec add + state.json 原子写)
- Kept: 3 (roadmap UX lane + spec console.status + artifact UX/REG-1 issue 登记)
- Archived: 0
- Rebuilt: 0 (0 P0, 不触发 /quality-sync --full)

## Files Modified (16 files)
- .workflow/codebase/doc-index.json (TC-005 + last_updated)
- .workflow/codebase/tech-registry/signal-risk-layer.md (ScalingPosition 删 + ISS-012 Note)
- .workflow/codebase/tech-registry/web-station.md (UX + fonts/)
- .workflow/codebase/tech-registry/cli-entry.md (行号 + REG-1/UX Note)
- .workflow/codebase/tech-registry/common-foundation.md (RiskConfig ISS-012 字段)
- .workflow/codebase/feature-maps/risk-controls.md (ScalingPosition 删)
- .workflow/codebase/feature-maps/cli.md (行号表对齐)
- .workflow/specs/coding-conventions.md (+2 spec entry: config-sourced baseline + credential redaction)
- .workflow/specs/architecture-constraints.md (S-20260705-revk +web XSS choke-point)
- .workflow/specs/test-conventions.md (+2 patterns: 静态 guard + config schema drift guard)
- .workflow/roadmap.md (Phase 2 post-verify 注记)
- .workflow/state.json (last_drift_realign + key_decisions +4, 原子写)

## Backup
- Location: .workflow/.trash/drift-realign-20260728T210000/ (13 文件备份)

## Auto-Rebuilt
- /quality-sync --full triggered: no (0 P0)
- /manage-codebase-rebuild suggested: no

## Notes
- 上轮 drift-realign (2026-07-28T17:08, drift-report-20260728.md) 声称已清 doc-index.json TC-005 scaling_position_sizer.py, 但磁盘实际未落盘 (TC-005 仍含 stale 符号)。本轮 DFT-7f3a2c1b 修正此遗漏。
- 上轮 drift-realign 的 drift-log.jsonl 末尾 last_drift_realign 时间戳未写入 state.json (state.json 仍 2026-07-26T10:40)。本轮 DFT-a7e6b0c1 修正此 stale timestamp。
- ISS-012 / UX / REG-1 三批 code commit 的文档对齐本轮闭环。REG-1 root pattern (generic except Exception swallows framework exceptions) 已在 tester wisdom contribution (tester-edge-cases-20260728.md) 记录, 本轮 spec coding-conventions 追加对应 spec entry (DFT-9b2c4e71) 作通则。
