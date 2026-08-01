# Harvest Report — 2026-07-30

## Source

Session: M4 v0.2 多 Symbol 扩展（Grill → Brainstorm → Analysis ×2 → Implementation Phase 1-5）

## Extracted Fragments

| # | Fragment | Category | Confidence | Routed To |
|---|----------|----------|------------|-----------|
| F1 | Pending 台账 reserve/confirm/release 三元语义 | architecture-pattern | high | knowhow |
| F2 | 多 symbol 扩展六项架构决策（Grill locked） | architecture-decision | high | knowhow |
| F3 | TOCTOU 四象限 timeout 决策矩阵 | safety-pattern | high | knowhow |
| F4 | partial_confirm 必须用 cumulative notional | pitfall | high | knowhow |
| F5 | 策略实例跨 symbol 状态污染 | pitfall | high | knowhow |
| F6 | CCXT exchange 实例共享约束 | constraint | high | knowhow |
| F7 | PaperGateway partial_fill_ratio 测试模式 | testing-pattern | medium | knowhow |

## Routing Summary

- **knowhow**: 7 entries created
- **spec**: 0 (existing specs already cover Fail-Closed / Kill Switch / ISS tracking)
- **issues**: 0 (all identified issues resolved during implementation)
- **wiki**: 0

## Dedup Check

- harvest-log.jsonl: 不存在（首次 harvest）
- 现有 knowhow/: 空目录
- 无重复

## Next Steps

- Phase 6 集成测试待编写（M4-6.1 ~ M4-6.9）
- 建议: `/quality-retrospective` 在 Phase 6 完成后做全阶段回顾
