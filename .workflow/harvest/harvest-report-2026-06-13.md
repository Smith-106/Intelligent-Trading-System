# Harvest Report — 2026-06-13

## Sources

| # | Source Type | ID | Title | Path | Files |
|---|-------------|----|-------|------|-------|
| 1 | analysis | ANL-001 | Intelligent Trading System 性能分析 | scratch/20260606-analyze-intelligent-trading-performance | 5 |
| 2 | brainstorm | brainstorm-strategies | 新策略方向 Brainstorm | scratch/20260602-brainstorm-new-strategies | 1 |
| 3 | plan | PLAN-001 | P1 四策略实现计划 | scratch/20260602-plan-P1-strategy-implementation | 1 |
| 4 | brainstorm | brainstorm-elliott | 柳玉东波浪理论交易系统 Brainstorm | scratch/brainstorm-elliott-wave-20260601 | 3+子目录 |
| 5 | plan | PLN-elliott-wave | 波浪理论实现计划 | scratch/20260601-plan-elliott-wave | 2 |
| 6 | plan | PLN-quality-fixes | 质量修复计划 | scratch/20260530-plan-quality-fixes | 1 |
| 7 | verify | VERIFY-001 | 质量循环验证 | scratch/20260530-verify-quality-loop | 1 |
| 8 | review | REVIEW-001 | 六维代码审查 | scratch/20260530-verify-quality-loop | 1 |

## Extraction Summary

- Fragments found: 27
- Filtered by confidence ≥ 0.5: 20
- Duplicates skipped: 7

### Duplicates Skipped

| Fragment | Reason |
|----------|--------|
| VectorBTEngine → BacktestEngine 重命名 | Already in specs/debug-notes.md |
| 层级边界定义 (L1→L6 单向依赖) | Already in specs/architecture-constraints.md |
| RedisCache 懒导入修复 | Already applied (ANL-001 Wave1) and recorded in debug-notes |
| Optuna GPSampler 缺少 fallback | Low confidence + partially addressed |
| FactorRegistry 被绕过 | Low confidence + documented as extension point |
| CLI _signal_fn closure 捕获错误作用域 | Low severity, already in VERIFY-001 as GAP-011 |
| DSR verify_data_shuffling() 空操作 | Low confidence, pending implementation decision |

## Routing Results

### Wiki (6 entries)

| # | Type | Slug | Title | Status |
|---|------|------|-------|--------|
| 1 | note | note-strategy-hotpath-recompute | 在线策略路径每根 bar 重建 DataFrame | CREATED |
| 2 | note | note-validation-multiplicative-cost | 验证 gate 组合放大优化成本 | CREATED |
| 3 | note | note-data-append-rewrite | DataStore/FeatureStore 追加写入重写分区 | CREATED |
| 4 | knowhow | knowhow-runtime-bottleneck-insight | 运行时瓶颈在策略重计算 | CREATED |
| 5 | knowhow | knowhow-zigzag-overlap-consensus | 多参数 ZigZag 交叉验证取 >80% 重叠 | CREATED |
| 6 | knowhow | knowhow-baseline-before-optimization | 性能优化先恢复 Benchmark 可复现性 | CREATED |

### Spec (7 entries)

| # | Type | Target File | Content (truncated) | Status |
|---|------|-------------|---------------------|--------|
| 1 | decision | architecture-constraints.md | 保持 generate_signals(df) 为研究 API | ADDED |
| 2 | decision | architecture-constraints.md | 新增策略顺序 P1→P2→P3→P4 | ADDED |
| 3 | decision | architecture-constraints.md | W3 铁律双模式 | ADDED |
| 4 | decision | architecture-constraints.md | DivergenceDetector 强制浪级比较 | ADDED |
| 5 | decision | architecture-constraints.md | ScalingPosition → RiskEngine 交互协议 | ADDED |
| 6 | decision | architecture-constraints.md | 波浪理论集成到六层架构，纯规则引擎 | ADDED |
| 7 | pattern | coding-conventions.md | 策略双模式: generate_signals + on_bar | ADDED |

### Issue (7 entries)

| # | Severity | Title | ID | Status |
|---|----------|-------|-----|--------|
| 1 | high | CPCV 创建 O(n²) 子 DataFrame 副本 | ISS-20260613-001 | CREATED |
| 2 | high | FeatureStore(L1) 导入 IndicatorEngine(L2) | ISS-20260613-002 | CREATED |
| 3 | high | OKXGateway 无 WebSocket 订阅实现 | ISS-20260613-003 | CREATED |
| 4 | high | Logging 可能泄漏 API Key 片段 | ISS-20260613-004 | CREATED |
| 5 | medium | CLI 不传递日期过滤给 DataStore.query() | ISS-20260613-005 | CREATED |
| 6 | medium | 增量策略逻辑可能与向量化逻辑漂移 | ISS-20260613-006 | CREATED |
| 7 | medium | ZigZag min_overlap>80% 可能导致信号缺失 | ISS-20260613-007 | CREATED |

## Provenance Log

- `.workflow/harvest/harvest-log.jsonl` — 20 entries with fragment_id, source, routing target, confidence

## Next

→ Review wiki entries: maestro wiki list --type note
→ Triage issues: /manage-issue list --source harvest
→ Connect wiki graph: /wiki-connect --fix
→ View specs: /spec-load --role implement
→ Full retrospective: /quality-retrospective
