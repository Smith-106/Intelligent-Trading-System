# F-006 — 分批建仓/出场策略

> Role: test-strategist | Related decisions: TS-07

## Architecture

分批建仓/出场策略扩展 PositionSizer，位于 L4/L5 层。测试架构 MUST 分为：

1. **仓位计算层**：验证试仓/加仓/追仓的仓位比例计算
2. **建仓条件层**：验证各阶段建仓的触发条件
3. **出场策略层**：验证分批出场的逻辑
4. **风控集成层**：验证与 PositionSizer 和 RiskEngine 的交互

测试模块位于 `tests/unit/execution/test_scaling_position.py`。

## Interface Contract

分批建仓暴露以下测试接口：

- `compute_trial_position(capital, risk_pct, entry_price, stop_price) -> Position` — 计算试仓仓位
- `compute_add_position(existing_position, wave_confirmation, capital) -> Position` — 计算加仓仓位
- `compute_chase_position(existing_position, momentum_signal, capital) -> Position` — 计算追仓仓位
- `compute_exit_plan(position, wave_stage, critical_levels) -> ExitPlan` — 计算出场计划
- `get_total_exposure() -> float` — 获取当前总敞口

## Constraints (RFC 2119)

- 试仓仓位 MUST 限制在总资金的 10%-15%
- 加仓仓位 MUST 限制在总资金的 20%-30%
- 追仓仓位 MUST 限制在总资金的 10%-15%
- 总敞口 MUST NOT 超过总资金的 60%（含所有在建仓位）
- 加仓 MUST 在浪型确认后才能触发（如浪3突破浪1高点确认后）
- 追仓 MUST 在强趋势确认后才能触发（如浪3延伸超过 1.618 扩展位）
- 分批出场 MUST 在浪5末端分批减仓（第一笔 50%、第二笔 30%、第三笔 20%）
- 止损 MUST 对所有在建仓位统一执行，不区分试仓/加仓/追仓

## Test Approach

### 单元测试

**仓位比例计算测试**：
- 给定不同资金量和风险参数，验证试仓/加仓/追仓的仓位比例
- 边界场景：小资金（总资金仅够试仓）、大资金（加仓+追仓后未超 60% 上限）
- 仓位叠加测试：试仓 + 加仓 + 追仓的总敞口 MUST ≤ 60%

**建仓条件测试**：

| 阶段 | 触发条件 | 仓位比例 | 测试 case |
|------|---------|---------|----------|
| 试仓 | 浪2回撤企稳 / 浪1突破初期 | 10-15% | 5 |
| 加仓 | 浪3确认突破浪1高点 | 20-30% | 5 |
| 追仓 | 浪3延伸超过 1.618 扩展位 | 10-15% | 5 |

- 每个阶段 MUST 验证：条件满足时正确建仓、条件不满足时不建仓
- 跨阶段 MUST 验证：前一阶段仓位未建时，后续阶段 MUST NOT 触发

**出场策略测试**：
- 分批出场比例验证：50% + 30% + 20% = 100%
- 出场触发条件：浪5末端信号（通道线突破 / 背离确认 / 临界位失守）
- 止损出场：所有在建仓位统一止损，不按比例分批

**风控集成测试**：
- PositionSizer 接口兼容性：验证扩展后的 PositionSizer 仍支持原有接口
- RiskEngine 交互：验证 RiskEngine 对总敞口的检查（≤60%）
- Kill Switch 交互：连续止损时，所有在建仓位 MUST 一次性清空

### 集成测试

**完整建仓-出场流程**：
- 模拟一个完整的浪1→浪5 周期
- 试仓（浪2企稳）→ 加仓（浪3确认）→ 追仓（浪3延伸）→ 分批出场（浪5末端）
- 验证每个阶段的仓位变化和总敞口
- 验证最终盈亏计算的正确性

**异常场景测试**：
- 浪2企稳后试仓，但浪3未确认即回落 → 触发试仓止损
- 浪3确认后加仓，但浪4调整过深 → 触发部分止损
- 加仓后立即触发数浪失效 → 全部仓位止损

### 测试数据 Fixtures

```
fixtures/
├── scaling_cases/
│   ├── full_cycle_scaling.json    # 完整周期分批建仓
│   ├── partial_cycle_scaling.json # 部分周期（仅试仓）
│   └── failed_cycle_scaling.json  # 失败周期（触发止损）
└── position_cases/
    ├── small_capital.json         # 小资金场景
    ├── large_capital.json         # 大资金场景
    └── multi_position.json        # 多仓位并行场景
```

## TODOs

- [ ] 确定试仓/加仓/追仓的精确仓位百分比（在 10-15% / 20-30% / 10-15% 范围内选定具体值）
- [ ] 定义总敞口上限的配置化方案（当前硬编码 60%，考虑配置外置）
- [ ] 设计多仓位并行时的资金分配算法
- [ ] 参考 [F-005](analysis-F-005-wave-signal-risk.md) 确认止损对分批建仓的影响
