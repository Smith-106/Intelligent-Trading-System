# F-003 — 波浪通道线 + 成交量/MACD背离验证

> Role: test-strategist | Related decisions: TS-04

## Architecture

波浪通道线和背离验证位于 L2 指标层，作为浪型识别的辅助确认手段。测试架构 MUST 分为：

1. **通道线计算层**：验证通道线的绘制和突破判定
2. **MACD背离层**：验证 MACD 背离的识别逻辑
3. **成交量背离层**：验证成交量背离的识别逻辑
4. **组合确认层**：验证多种确认信号的组合判断

测试模块位于 `tests/unit/indicators/test_wave_channel.py` 和 `tests/unit/indicators/test_divergence.py`。

## Interface Contract

通道线和背离验证暴露以下测试接口：

- `compute_wave_channel(wave1_high, wave3_high, wave2_low) -> ChannelLine` — 计算波浪通道线
- `detect_macd_divergence(prices, macd_line, signal_line) -> list[Divergence]` — 检测 MACD 背离
- `detect_volume_divergence(prices, volumes) -> list[Divergence]` — 检测成交量背离
- `confirm_wave_endpoint(wave_pattern, channel, divergences) -> ConfirmationResult` — 综合确认浪型终点

## Constraints (RFC 2119)

- 波浪通道线 MUST 连接浪1和浪3高点画上轨，浪2低点画下轨平行线
- MACD 背离 MUST 仅在浪5位置检测顶背离，在浪C位置检测底背离
- 成交量背离 MUST 验证浪5成交量递减模式（相比浪3）
- 背离检测 MUST 要求至少 2 个连续的极值点形成背离
- 通道线突破判定 MUST 设置容差范围（如通道价格的 0.5%）
- 组合确认 MUST 至少满足 2/3 条件才判定为高置信确认

## Test Approach

### 单元测试

**通道线计算测试**：
- 给定浪1、浪3高点和浪2低点，验证通道线斜率和截距计算
- 通道线延长测试：验证通道线对浪5终点的预测精度
- 边界场景：浪1和浪3高点接近水平（几乎零斜率）、极端倾斜通道

**MACD 背离测试**：
- 顶背离场景：价格创新高但 MACD 未创新高 — 合法背离 10 个 case
- 底背离场景：价格创新低但 MACD 未创新低 — 合法背离 10 个 case
- 伪背离场景：MACD 和价格同步 — 不应检测到背离 10 个 case
- 边界场景：MACD 极值接近零线、MACD 极值间距过小

**成交量背离测试**：
- 浪5成交量递减：浪5成交量低于浪3 — 正常背离
- 成交量放大确认：浪3成交量高于浪1 — 正常确认
- 异常成交量：浪5成交量异常放大 — 不符合浪5特征

### 集成测试

**组合确认测试**：
- 通道线突破 + MACD 背离 + 成交量递减 = 高置信浪5终点确认
- 仅有 1/3 条件满足 = 低置信，策略 SHOULD 谨慎入场
- 通道线预测 vs 背离信号冲突时的处理逻辑

**历史场景回测**：
- 选取至少 30 个已知浪5终点的历史场景
- 验证通道线和背离组合确认的命中率
- 计算确认信号与实际终点的时间偏差

### 测试数据 Fixtures

```
fixtures/
├── divergence_cases/
│   ├── macd_top_divergence.json    # MACD 顶背离样本
│   ├── macd_bottom_divergence.json # MACD 底背离样本
│   ├── volume_divergence.json      # 成交量背离样本
│   └── no_divergence.json          # 无背离对照样本
├── channel_cases/
│   ├── standard_channel.json       # 标准通道线
│   ├── flat_channel.json           # 水平通道
│   └── steep_channel.json          # 陡峭通道
└── combined_cases/
    ├── high_confidence_exit.json   # 高置信浪5终点
    └── low_confidence_exit.json    # 低置信浪5终点
```

## TODOs

- [ ] 收集历史中 MACD 背离成功/失败的案例样本
- [ ] 定义背离检测的参数标准（极值间距、最小幅度差）
- [ ] 确定组合确认的权重分配方案
- [ ] 参考 [F-001](analysis-F-001-zigzag-wave-identifier.md) 确认通道线与浪型识别的依赖关系
