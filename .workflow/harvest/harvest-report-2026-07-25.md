# Harvest Report — 2026-07-25

## Source
- Type: scratchpad (execute run report.md + 5 wave commits)
- ID: 20260725-003-execute
- Path: .workflow/sessions/maestro-multi-book-reconcile-20260725-113526/runs/20260725-003-execute/
- Session: maestro-multi-book-reconcile-20260725-113526 (chain step-003-harvest, args --auto/-y)

## Extraction Summary
- Fragments found: 10 (9 decision/pattern + 1 caveat-risk)
- Filtered by confidence ≥ 0.5: 10
- Duplicates skipped: 1 (caveat OKXGateway ws fill-callback → covered by ISS-20260613-003 "OKXGateway 无 WebSocket 订阅实现")
- Routed: 9 spec, 0 wiki, 0 issue

## Routing Results

### Spec (9 entries — all ADDED, no dup)

| # | Category | SID | Title | Conf | File |
|---|----------|-----|-------|------|------|
| 1 | arch | S-20260725-y8sf | L4 单一权威账本: engine.submit 统一 L4 fill 更新 + L5 薄路由委托 + PaperGateway 移除第三套 _cash | 0.95 | architecture-constraints.md |
| 2 | arch | S-20260725-nxzl | 翻仓 realized PnL 归因与 cash 解耦(保守路径): closing_qty*sign 累计 | 0.90 | architecture-constraints.md |
| 3 | arch | S-20260725-ue4p | partial-fill cumulative 契约: applied_filled_qty 防重复 fill 双计 | 0.92 | architecture-constraints.md |
| 4 | arch | S-20260725-0du3 | 构造顺序循环懒绑定: set_portfolio 重绑共享 L4 | 0.85 | architecture-constraints.md |
| 5 | arch | S-20260725-58tc | daily_loss total-vs-baseline + 日切锚定 + warmup guard | 0.90 | architecture-constraints.md |
| 6 | coding | S-20260725-3zl0 | 翻仓 realized 归因代码模式: closing_qty*sign + snapshot 暴露 | 0.88 | coding-conventions.md |
| 7 | coding | S-20260725-j4x6 | cumulative-fill delta 守卫代码模式 + PARTIAL 状态保留 | 0.90 | coding-conventions.md |
| 8 | coding | S-20260725-jabg | L5 PositionManager 薄路由委托模式 + PaperGateway 本地视图 | 0.88 | coding-conventions.md |
| 9 | debug | S-20260725-33y2 | PARTIAL 状态静默降级 SUBMITTED bug 修复: 状态白名单补 PARTIAL | 0.92 | debug-notes.md |

### Wiki (0 entries)
无 — 本批知识是可执行规范/决策/代码模式，归 spec；无通用 knowhow/note 适合 wiki 图。

### Issue (0 entries)
无新建 — 唯一 caveat（OKXGateway ws fill-callback 缺失）已被现有 ISS-20260613-003（OKXGateway 无 WebSocket 订阅实现）覆盖，dedup 跳过。

## Skipped
| Fragment | Reason |
|----------|--------|
| OKXGateway 无 ws fill-callback, live partial fill 自动感知需 ws(watch_orders) | [SKIP-DUP] covered by ISS-20260613-003 "OKXGateway 无 WebSocket 订阅实现" — ws 订阅缺失是更大父题，fill-callback 是其子集 |

## Spec Relationship Pre-check (invariant #5)
所有 9 条 spec 与现有 spec 关系 = **independent**（去重检查确认 .workflow/specs/*.md 无 reconcile/realized/partial-fill/cumulative/多-book/单一权威/薄路由/daily_baseline/翻仓/applied_filled 相关条目）。无 supersede、无 conflict 元数据附加。

## Provenance
- Log: .workflow/harvest/harvest-log.jsonl (9 records, fragment_id HRV-{8hex} 确定性 hash from source_id+sid)
- Timestamp: 2026-07-25T14:14:19Z

## Source Coverage
本批 harvest 提取自 execute run report.md 的 frontmatter（6 decisions + 5 caveats + next）+ 正文 DoD（G1-G4 + paper-live parity）+ 5 个 wave commit（7e781a8/062a7b5/90b3eff/b0177e0/06a8d93）。所有可执行决策与代码模式已固化为 spec；唯一未缓解风险已映射到现有 issue。
