# Harvest Report — 2026-07-24

## Source
- Type: debug (odyssey-debug session)
- ID: 20260724-debug-odyssey-l6-sibling-sinks
- Path: .workflow/scratch/20260724-debug-odyssey-l6-sibling-sinks/

## Extraction Summary
- Fragments found: 9 (from understanding.md 9 sections)
- Filtered by confidence ≥ 0.5: 9
- Duplicates skipped: 7 (already persisted in S_RECORD)
- Net routed: 2

## Routing Results

### Spec (1 entry)
| # | Type | sid | Title | Status |
|---|------|-----|-------|--------|
| 1 | learning | S-20260724-3jyz | 幂等状态下沉到模块全局致测试顺序依赖 — 测试须显式重置全局 | ADDED |

### Wiki (1 entry)
| # | Type | slug | Title | Status |
|---|------|------|-------|--------|
| 1 | knowhow | knowhow-concurrent-agent-session-collision | 并发 Agent 会话并行提交同仓 — ancestry 检查 + 工作区审计防冲突 | CREATED |

## Skipped (dedup)
| Fragment | Reason |
|----------|--------|
| MonitoringSink Protocol 注入模式 | SKIP-DUP: coding-conventions-009 (S-20260724-3i37, updated this session) |
| in-function lazy-import = audit-evasion | SKIP-DUP: architecture-constraints-013 (S-20260724-02ek) |
| Grep-after-Edit 缓存陷阱 | SKIP-DUP: learnings INS-ca90827c (added this session S_RECORD) |
| TradingSession sink 赋值顺序 | SKIP-DUP: implicit in coding-conventions-009 |
| ISS-021 PaperGateway reduceOnly parity | SKIP-DUP: concurrent session committed 7aa7139 + closed ISS-021 |
| ISS-022 consolidate_signals avg_strength | SKIP-DUP: concurrent session committed cc72b9e + closed ISS-022 |
| ISS-019 RECORD spec固化 | SKIP-DUP: concurrent session committed a634758 |

## Notes
- Source session already ran S_RECORD (spec/learning persistence) during the
  odyssey-debug loop; harvest captured only the 2 fragments NOT already in stores.
- Concurrent maestro-cli session committed ISS-021/022/019-RECORD during this
  odyssey — its work appears as SKIP-DUP (already closed in issue-history.jsonl).
- The 2 routed items fill genuine gaps: metrics-server idempotency test gotcha
  (learning) + concurrent-agent collision playbook (knowhow).
