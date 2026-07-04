# F-005 — 波浪信号生成器 + 数浪失效规则 + 硬/软止损

> Role: test-strategist | Related decisions: TS-06

## Architecture

波浪信号生成器和风控规则位于 L4 信号风控层，是资金安全的关键防线。测试架构 MUST 分为：

1. **信号生成层**：验证波浪信号的正确生成和传递
2. **数浪失效层**：验证失效规则的触发和信号撤销
3. **止损层**：验证硬止损和软止损的触发和执行
4. **风控集成层**：验证与 RiskEngine 和 PositionSizer 的交互

测试模块位于 `tests/unit/signal/test_wave_signal.py` 和 `tests/integration/test_wave_risk.py`。

## Interface Contract

波浪信号生成器和风控暴露以下测试接口：

- `generate_wave_signal(wave_pattern, confidence) -> Signal` — 生成波浪交易信号
- `check_invalidation(wave_pattern, current_price) -> InvalidationResult` — 检查数浪失效
- `compute_hard_stop(wave_pattern, critical_levels) -> float` — 计算硬止损价位
- `compute_soft_stop(wave_pattern, market_context) -> float` — 计算软止损价位
- `on_invalidation(signal, invalidation) -> Action` — 失效时的信号处理

## Constraints (RFC 2119)

- 数浪失效规则 MUST 在关键价位突破时立即触发
- 硬止损 MUST 在数浪失效时无条件执行，不依赖市场流动性
- 软止损 SHOULD 在市场出现异常波动时触发，允许滑点容忍
- 硬止损价位 MUST 基于多空临界位计算，不使用固定百分比
- 软止损价位 SHOULD 考虑当前市场波动率（ATR）动态调整
- 信号生成 MUST 包含置信度评分，低置信信号 SHOULD 降低仓位
- 失效信号 MUST 在 1 根K线内完成撤销和止损触发
- 止损执行 MUST 通过 Kill Switch 机制保障（实盘模式）

## Test Approach

### 单元测试

**信号生成测试**：
- 给定不同浪型和置信度，验证信号方向（做多/做空/空仓）
- 信号参数验证：入场价、目标价、止损价、仓位比例
- 低置信信号测试：置信度 < 0.5 时 SHOULD 降低仓位或不开仓
- 信号去重：相同浪型不重复生成信号

**数浪失效规则测试**：

| 失效场景 | 触发条件 | 预期动作 | 测试 case 数 |
|---------|---------|---------|-------------|
| 浪2失效 | 跌破浪1起点 | 撤销所有做多信号 + 硬止损 | 5 |
| 浪4失效 | 进入浪1区域 | 调整浪型方案 + 软止损 | 5 |
| 浪5失效 | 突破通道线上轨后回落 | 退出浪5仓位 | 5 |
| C浪失效 | 跌破A浪终点 | 撤销做空信号 + 硬止损 | 5 |
| 方案切换 | 原方案失效，新方案确立 | 撤销旧信号 + 生成新信号 | 3 |

**硬止损测试**：
- 止损价位 MUST 等于临界位价格（无偏移）
- 止损触发后 MUST 立即执行，不等待下一根K线
- 多个仓位同时触发硬止损时的处理顺序

**软止损测试**：
- 软止损价位 = 临界位 + N * ATR（N 由配置决定）
- 市场波动率异常（ATR 突然放大 3x）时的软止损调整
- 软止损触发后的仓位减半逻辑

### 集成测试

**风控集成测试**：
- 信号生成 → RiskEngine.check() → PositionSizer.size() → ExecutionEngine.submit() 完整链路
- 数浪失效 → 信号撤销 → 止损执行 → 仓位清空 完整链路
- Kill Switch 触发场景：连续止损 3 次 → 暂停交易

**实盘模拟测试**：
- 使用 PaperGateway 模拟实盘环境
- 验证止损订单的执行价格与预期止损价的偏差
- 标记 `@pytest.mark.live`，仅在特定环境执行

### 测试数据 Fixtures

```
fixtures/
├── invalidation_cases/
│   ├── wave2_invalidation.json
│   ├── wave4_invalidation.json
│   ├── wave5_invalidation.json
│   └── c_wave_invalidation.json
├── stop_loss_cases/
│   ├── hard_stop_triggers.json
│   ├── soft_stop_triggers.json
│   └── kill_switch_triggers.json
└── risk_scenarios/
    ├── flash_crash.json         # 闪崩场景
    ├── gap_down.json            # 跳空下跌
    └── slow_grind.json          # 缓慢阴跌
```

## TODOs

- [ ] 定义数浪失效的完整规则清单（与 subject-matter-expert 确认）
- [ ] 确定硬止损和软止损的 ATR 倍数参数
- [ ] 设计 Kill Switch 触发条件的测试场景
- [ ] 参考 [F-001](analysis-F-001-zigzag-wave-identifier.md) 确认浪型识别对失效判定的影响
- [ ] 参考 [F-006](analysis-F-006-scaling-position.md) 确认分批建仓的止损处理
