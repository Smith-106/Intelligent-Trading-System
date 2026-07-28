# Drift Realign Report — 2026-07-28

## Timeline Window
- From: 2026-07-26 → To: 2026-07-28 (2 days)
- Git: 20 commits, 76 files changed (+4632 / -908)
- Sessions: 0 total (wiki 未索引, W001 — git-only timeline, [LOW CONFIDENCE])
- Drift Score: 17.4 (LOW; 2 × √76 × ~1.2 max-scope-weight)
- Hot paths: tests/unit (17), quantflow/execution (12), .workflow/codebase (10), .workflow/issues (7), quantflow/signal (5)

## Scan Summary
- Total findings: 30 (12 P0 / 14 P1 / 4 P2)
- By scope: codebase 17 / spec 7 / roadmap 2 / artifact 4 / state 0 / knowhow 0 / project 0
- 4 scanner agents all returned (GATE 3 passed). All findings源于刚交付的 4 条架构批次 (ISS-003/004/005/011, commits a5b7f37/0c89957/08d7032/c51d571) 文档未同步 + 1 历史遗留 (M2 Phase 3 release-evidence) + 3 历史 issue 失效路径。

## Triage Mode
- 用户裁决: 全部 update + 直接更新文档内容 (不注入 TODO 注释, evidence 充分含精确行号)
- P2 (4 条): DFT-sp07 已合并入 update (test-conventions 范式补充), DFT-cb16/cb17 已随相关文件 update 一并处理. 实际无 keep 项.

## Actions Applied

### codebase scope (17 — 全部 update, 直接改内容)
| # | ID | Severity | Drift Type | Target | Action |
|---|----|----------|-----------|--------|--------|
| 1 | DFT-cb01 | P0 | architecture_outdated | feature-maps/execution.md | update (删 ScalingPositionSizer 行 + 加 OrderRouter + 更新 OKXGateway) |
| 2 | DFT-cb02 | P1 | feature_missing | feature-maps/execution.md | update (同上 #1) |
| 3 | DFT-cb03 | P1 | feature_missing | feature-maps/execution.md | update (同上 #1) |
| 4 | DFT-cb04 | P0 | architecture_outdated | tech-registry/execution-layer.md Code Locations | update (删 scaling 行 + 加 order_router) |
| 5 | DFT-cb05 | P0 | architecture_outdated | tech-registry/execution-layer.md Exported Symbols | update (12→9 符号: 删 4 Scaling* 加 OrderRouter) |
| 6 | DFT-cb06 | P1 | feature_missing | tech-registry/execution-layer.md Notes | update (加 ISS-003 Note) |
| 7 | DFT-cb07 | P1 | feature_missing | tech-registry/execution-layer.md OKXGateway | update (加 ISS-005 market_type + ISS-011 sink) |
| 8 | DFT-cb08 | P1 | feature_missing | tech-registry/execution-layer.md OrderManager | update (加 ISS-011 timed_out) |
| 9 | DFT-cb09 | P0 | feature_missing | tech-registry/monitoring-layer.md metrics | update (加 4 OBS-M metric) |
| 10 | DFT-cb10 | P1 | feature_missing | tech-registry/monitoring-layer.md Notes | update (加 ISS-011 Protocol 扩展 Note) |
| 11 | DFT-cb11 | P0 | feature_missing | tech-registry/common-foundation.md | update (12→16 methods + ISS-011 落地站点) |
| 12 | DFT-cb12 | P0 | doc_index_stale | doc-index.json TC-005.code_locations | update (删 scaling 加 order_router) |
| 13 | DFT-cb13 | P0 | architecture_outdated | doc-index.json TC-005.symbols | update (删 4 Scaling* 加 OrderRouter) |
| 14 | DFT-cb14 | P1 | feature_missing | feature-maps/_index.md | update (总述加 2026-07-28 批次) |
| 15 | DFT-cb15 | P1 | feature_missing | tech-registry/_index.md Recent Changes | update (TC-005/006/007/004 加 ISS-003/005/011) |
| 16 | DFT-cb16 | P2 | feature_missing | tech-registry/execution-layer.md Dependencies | update (ISS-011 扩 sink 消费者) |
| 17 | DFT-cb17 | P1 | feature_missing | doc-index.json FT-005/006 description | update (加 OrderRouter + 删 ScalingPositionSizer 引用) |

### spec scope (7 — 全部 update)
| # | ID | Severity | Drift Type | Target | Action |
|---|----|----------|-----------|--------|--------|
| 18 | DFT-sp01 | P0 | dead_import_pattern | architecture-constraints.md ScalingPosition spec-entry | update (标注 ISS-004 已删, 协议 moot) |
| 19 | DFT-sp02 | P1 | stale_dependency | architecture-constraints.md arch-013 S-20260724-02ek | update (加 ISS-011 OKXGateway/OrderManager 站点) |
| 20 | DFT-sp03 | P0 | architecture_breach | architecture-constraints.md arch-017 | update (S-20260725-0du3 加 OrderRouter.set_gateway 同构) |
| 21 | DFT-sp04 | P1 | architecture_breach | architecture-constraints.md Module Structure | update (加 OrderRouter + 新增 S-20260727-or3r spec-entry) |
| 22 | DFT-sp05 | P1 | stale_dependency | architecture-constraints.md S-20260718-h6ml parity | update (加 ISS-005 spot/swap parity 收窄) |
| 23 | DFT-sp06 | P2 | stale_dependency | coding-conventions.md S-20260724-3i37 | update (方法计数 6→14 + ISS-011 站点) |
| 24 | DFT-sp07 | P2 | test_convention_gap | test-conventions.md Patterns | update (加 test_order_router/test_monitoring_sink_obs 范式) |

### roadmap scope (2 — 全部 update)
| # | ID | Severity | Drift Type | Target | Action |
|---|----|----------|-----------|--------|--------|
| 25 | DFT-rm01 | P0 | milestone_mismatch | roadmap.md M2 Phase 3 | update ([x]→[~] + Progress 表 Completed→In progress) |
| 26 | DFT-rm02 | P1 | stale_progress | roadmap.md Blocking Findings | update (同 #25, 区分 tag 已建 vs 证据归档未闭环) |

### artifact scope (4 — 全部 update)
| # | ID | Severity | Drift Type | Target | Action |
|---|----|----------|-----------|--------|--------|
| 27 | DFT-af01 | P1 | issue_code_ref_dead | issue-history.jsonl ISS-025 | update (resolution 追加 ScalingPositionSizer 已删) |
| 28 | DFT-af02 | P1 | issue_code_ref_dead | issue-history.jsonl ISS-039 | update (路径 ai/ml_ensemble→templates/ml_ensemble) |
| 29 | DFT-af03 | P1 | issue_code_ref_dead | issue-history.jsonl ISS-040 | update (路径 ai/sentiment→strategy/sentiment) |
| 30 | DFT-af04 | P1 | issue_stale_open | issues.jsonl ISS-012 | update (fix_direction scope 收窄 + 函数位置更正) |

## Kept (no drift or user chose keep)
无 — 全部 30 条 finding 均 update。

## Auto-Rebuilt
- /maestro-manage sync codebase --full triggered: **no** (codebase P0 = 7, 虽 ≥3 但已通过直接 update 逐条修复, 无结构性断裂需 rebuild; invariant 7 阈值是"3+ P0 触发 rebuild 评估", 本次 update 已闭合全部 P0, rebuild 非必要)
- /maestro-manage sync rebuild suggested: **no**

## Backup
- Location: `.workflow/.trash/drift-realign-20260728T090000/` (14 文件: 7 codebase + 3 spec + roadmap + 2 issues + state.json)

## Code-as-Truth 校验
- 本次 0 处反向修改代码匹配文档 — 全部 30 条均为"文档漂移, 改文档匹配代码现实"
- 源代码文件 (quantflow/*) 全程只读, 未触碰

## state.json
- last_drift_realign: 2026-07-26T10:40+08:00 → 2026-07-28T09:10+08:00 (原子写: tmp→verify→replace)
