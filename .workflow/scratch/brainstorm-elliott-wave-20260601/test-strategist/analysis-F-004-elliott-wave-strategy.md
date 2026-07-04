# F-004 — ElliottWaveStrategy（继承StrategyBase）+ 5种浪段交易规则

> Role: test-strategist | Related decisions: TS-05, TS-12

## Architecture

ElliottWaveStrategy 位于 L3 策略层，继承 StrategyBase，实现 5 种浪段交易规则。测试架构 MUST 分为：

1. **策略接口层**：验证 StrategyBase 接口实现的正确性
2. **浪段规则层**：验证 5 种浪段交易规则的信号生成逻辑
3. **回测验证层**：验证策略在历史数据上的表现满足验收标准
4. **防过拟合层**：验证策略通过 CPCV/DSR/PBO/WFO 检验

测试模块位于 `tests/unit/strategy/test_elliott_wave.py` 和 `tests/integration/test_elliott_wave_strategy.py`。

## Interface Contract

ElliottWaveStrategy 暴露以下测试接口：

- `on_init(ctx: StrategyContext) -> None` — 策略初始化
- `on_bar(ctx: StrategyContext, bar: Bar) -> None` — 逐K线处理
- `generate_signals(df: pd.DataFrame) -> tuple[entries, exits]` — 信号生成
- `get_wave_rules() -> list[WaveRule]` — 获取当前激活的浪段规则

StrategyBase 接口测试 MUST 验证：
- `on_init` 正确加载 elliott_wave.yaml 配置
- `on_bar` 正确触发浪型识别和信号生成
- `generate_signals` 返回格式与 VectorBT 兼容

## Constraints (RFC 2119)

- 策略回测 MUST 使用 VectorBT 框架执行
- 回测交易数量 MUST ≥100 笔
- 回测验收标准 MUST 满足：胜率≥55%、盈亏比≥2:1、最大回撤≤15%、年化收益≥20%、夏普比率≥1.5
- 5 种浪段交易规则 MUST 独立可测试：浪1突破、浪2回撤、浪3主升、浪4调整、浪5末退
- 策略 MUST NOT 在浪型未确认时产生入场信号
- 策略 MUST 支持回测模式和实盘模式的一致性（TradingSession 统一）
- 防过拟合验证 MUST 通过 CPCV + DSR + PBO + WFO 全部四项检验

## Test Approach

### 单元测试

**StrategyBase 接口测试**：
- 验证 `on_init` 加载配置后，策略参数与 elliott_wave.yaml 一致
- 验证 `on_bar` 在不同浪型状态下产生正确的信号
- 验证 `generate_signals` 返回的 entries/exits 格式正确

**5 种浪段规则测试**：

| 浪段 | 入场条件 | 出场条件 | 测试重点 |
|------|---------|---------|---------|
| 浪1突破 | 突破前调整浪上边界 | 浪1目标价或浪2回撤开始 | 突破确认逻辑 |
| 浪2回撤 | 回撤至 0.618 位企稳 | 浪3突破浪1高点 | 回撤深度和企稳判定 |
| 浪3主升 | 突破浪1高点确认 | 浪3目标扩展位或浪4开始 | 浪3确认和目标追踪 |
| 浪4调整 | 回撤至 0.382 位企稳 | 浪5突破浪3高点 | 调整深度和企稳判定 |
| 浪5末退 | 浪5接近通道线上轨 | 背离确认或通道突破 | 退出信号可靠性 |

每种浪段规则 MUST 至少 5 个正向测试 case 和 3 个反向测试 case。

### 集成测试

**VectorBT 回测验证**：
- 使用 BTC/USDT 2020-2024 历史数据执行完整回测
- 验证回测结果满足 §6 验收标准
- 回测 MUST 包含交易成本（手续费 0.1%、滑点 0.05%）
- 回测 MUST 使用多参数组合，验证策略鲁棒性

**防过拟合验证管道**：
- CPCV（组合交叉验证）：6 组组合，至少 2 条路径通过
- DSR（偏斜度修正夏普比）：修正后夏普比 MUST > 1.0
- PBO（过拟合概率）：PBO MUST < 0.5
- WFO（步进前进优化）：至少 5 个窗口，每个窗口独立验证
- GO/NO-GO 门：全部四项检验通过才判定策略可用

### 回测报告模板

```
Elliott Wave Strategy Backtest Report
=====================================
Period: {start} - {end}
Symbol: {symbol}
Trades: {count}

Performance Metrics:
  Win Rate: {win_rate}% (target: ≥55%)
  Profit Factor: {pf} (target: ≥2:1)
  Max Drawdown: {mdd}% (target: ≤15%)
  Annual Return: {ann_ret}% (target: ≥20%)
  Sharpe Ratio: {sharpe} (target: ≥1.5)

Anti-Overfitting:
  CPCV: {pass_count}/{total_paths} paths
  DSR Sharpe: {dsr_sharpe}
  PBO: {pbo_value}
  WFO: {wfo_windows}/{total_windows} windows pass
  Gate: GO / NO-GO
```

## TODOs

- [ ] 确定回测数据的时间范围和交易对
- [ ] 定义 CPCV 的组合数量和路径要求
- [ ] 确定 WFO 的窗口大小和步进参数
- [ ] 设计 PBO 的训练/测试分割方案
- [ ] 参考 [F-005](analysis-F-005-wave-signal-risk.md) 确认风控规则对回测结果的影响
- [ ] 参考 [F-006](analysis-F-006-scaling-position.md) 确认分批建仓对盈亏比的影响
- [ ] 参考 [F-008](analysis-F-008-cli-config-backtest.md) 确认 CLI 回测命令的参数传递
