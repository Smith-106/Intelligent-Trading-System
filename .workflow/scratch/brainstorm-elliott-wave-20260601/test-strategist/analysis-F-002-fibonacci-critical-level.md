# F-002 — 斐波那契回撤/扩展计算器 + 多空临界位标注

> Role: test-strategist | Related decisions: TS-03

## Architecture

斐波那契计算器位于 L2 指标层，为策略层提供目标价和入场区计算支持。测试架构 MUST 分为：

1. **计算精度层**：验证斐波那契数值计算的数学正确性
2. **临界位标注层**：验证多空临界位的识别和标注逻辑
3. **动态更新层**：验证临界位随浪型更新的调整机制

测试模块位于 `tests/unit/indicators/test_fibonacci.py`。

## Interface Contract

斐波那契计算器暴露以下测试接口：

- `compute_retracement(high, low, levels=[0.236, 0.382, 0.5, 0.618, 0.786]) -> dict[float, float]` — 计算回撤位
- `compute_extension(wave_start, wave_end, retracement_end, levels=[1.0, 1.272, 1.618]) -> dict[float, float]` — 计算扩展位
- `identify_critical_levels(wave_pattern, fib_levels) -> list[CriticalLevel]` — 识别多空临界位
- `update_critical_levels(current_levels, new_wave_data) -> list[CriticalLevel]` — 动态更新临界位

## Constraints (RFC 2119)

- 斐波那契回撤位计算 MUST 精确到小数点后 4 位，相对误差 < 0.01%
- 标准回撤位 MUST 包含：0.236、0.382、0.5、0.618、0.786
- 标准扩展位 MUST 包含：1.0、1.272、1.618、2.0、2.618
- 多空临界位标注 MUST 明确标注：突破确认位、失守确认位、止损位
- 临界位随浪型更新 MUST 在 1 根K线内完成重新计算
- 计算器 MUST 支持双向计算（上涨浪和下跌浪）

## Test Approach

### 单元测试

**计算精度测试**：
- 给定精确的高低点，验证各回撤位计算结果
- 参数化测试：覆盖上涨浪和下跌浪两种方向
- 边界场景：高低点相同（零波动）、极端大波动（价格差 100x）
- 浮点精度：验证计算结果与预期值的相对误差

**扩展位计算测试**：
- 给定浪1起点、终点和浪2回撤终点，验证浪3目标扩展位
- 覆盖完整浪型：浪1→浪2→浪3、浪3→浪4→浪5、A浪→B浪→C浪
- 验证扩展位与回撤位的组合使用场景

**临界位识别测试**：
- 给定浪型结构和斐波那契位，验证临界位识别逻辑
- 浪2终点临界位：跌破则浪1→浪2→浪3 方案失效
- 浪4终点临界位：跌破则推动浪结构可能转为调整浪
- 浪5终点临界位：突破则可能进入延长浪

### 集成测试

**动态更新测试**：
- 模拟浪型更新场景，验证临界位的重新计算和通知
- 浪型方案切换场景：当原方案失效，新方案确立时，临界位的完整更新
- 多时间框架临界位对齐：验证周线临界位与 4H 临界位的一致性

### 测试数据 Fixtures

```
fixtures/
├── fibonacci_cases/
│   ├── btc_impulse_wave.json    # 推动浪斐波那契计算
│   ├── btc_corrective_wave.json # 调整浪斐波那契计算
│   └── edge_cases.json          # 边界场景
└── critical_levels/
    ├── wave2_critical.json      # 浪2临界位
    ├── wave4_critical.json      # 浪4临界位
    └── wave5_critical.json      # 浪5临界位
```

## TODOs

- [ ] 确定斐波那契计算的浮点精度标准
- [ ] 收集历史数据中临界位突破后的实际走势样本
- [ ] 设计临界位有效性的评估指标（突破后 N 根K线内的价格行为）
- [ ] 参考 [F-005](analysis-F-005-wave-signal-risk.md) 确认临界位与止损规则的关联
