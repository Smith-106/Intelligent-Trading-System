# Best Solution: 提升交易系统胜率（第二轮）

## 摘要

经过 3 轮 ACO 蚁群探索（12 只 ant，14 个任务空间节点），发现第一轮 P1-P4 实施后仍存在 **21 个系统性瓶颈**，分为 7 个修复集群，预计综合提升胜率 **+25-45%**。

---

## 收敛数据

| 指标 | 值 |
|------|-----|
| 总迭代数 | 3 |
| 总 ant 数 | 12 |
| 最佳 ant | ANT-2-1 (regime_detection 路径) |
| 最佳 self_score | 0.85 |
| Pheromone 最热边 | profit_target_calibration → trailing_stop_tuning (τ=1.99) |
| Entropy 变化 | 6.49 → 6.39 (递减，探索收窄) |

---

## 7 个修复集群（优先级排序）

### P1: on_bar() 出场机制缺失 [CRITICAL] ⚡
**影响**: +10-20% 胜率

4/6 策略的 `on_bar()` 路径（paper/live 模式）缺少全部出场机制：
- `trend_following.py:106-122` — 只有 `_latest_signal()`，无 profit_target、trailing stop、max_holding
- `mean_reversion.py:64-80` — 只检查 BB band proximity + RSI，无 profit_target 和 max_holding
- `volatility_breakout.py:114-130` — 只检查 ATR shrink + middle return
- `funding_rate.py:71-86` — 只检查 neutral zone + OI reversal
- `elliott_wave.py:70-74` — on_bar() 是空的

**修复**：为每个策略的 `on_bar()` 添加 profit_target、trailing stop、max_holding_bars 检查，与 `generate_signals()` 保持一致。

### P2: profit_target_exit() 仅支持 LONG 方向 [CRITICAL] ⚡
**影响**: +8-15% 胜率

`_runtime.py:167` — `target = entry_price * (1 + profit_take_pct)`, 检查 `close >= target`。
SHORT 头寸永远无法触发止盈，只能通过 max_holding_bars 超时退出（此时通常已亏损）。

**修复**：
```python
def profit_target_exit(close, entries, profit_take_pct, max_holding_bars, direction=None):
    # ... 对 SHORT: target = entry * (1 - pct), check close <= target
```

关联问题：`mean_reversion.py:138` 将 long+short entries 合并为单一布尔序列，导致 profit_target_exit 无法区分方向。需拆分为 `long_entries` 和 `short_entries`。

### P3: Regime 检测缺失 — 策略盲目发射 [CRITICAL] ⚡
**影响**: +8-15% 胜率

- `quantflow/` 全局 grep 'regime' 仅 `momentum_rotation.py:17` 文档注释
- `indicators/trend.py:100-125` 已实现 `adx()` 但从未被任何策略消费
- 趋势策略在震荡市发射（低胜率），均值回归在趋势市发射（低胜率）

**修复**：
- 在 `engine.py` 的 `on_bar()` 中计算 ADX
- ADX > 25: 允许 trend_following、volatility_breakout 入场
- ADX < 25: 允许 mean_reversion 入场
- 现有 `MTFAligner` (mtf_aligner.py) 可作为高时间帧确认过滤器

### P4: Trailing Stop 方向感知 + 缺失 [HIGH]
**影响**: +5-12% 胜率

**4 个子问题**：

| # | 问题 | 文件 | 修复 |
|---|------|------|------|
| 4a | trailing stop 仅跟踪最高价，SHORT 无保护 | trend_following.py:287, vol_breakout.py:391 | LONG: track highest HIGH; SHORT: track lowest LOW |
| 4b | 跟踪 CLOSE 而非 HIGH — 止损过紧 | 同上 | `highest = high.copy()` 而非 `close.copy()` |
| 4c | 4/6 策略完全没有 trailing stop | elliott_wave, funding_rate, momentum_rotation, mean_reversion | 添加 ATR-based trailing stop |
| 4d | ATR 倍数过宽 (code 3.0 vs YAML 1.5) | trend_following.py:56 | 修复 YAML-key 映射使 YAML 值生效 |

### P5: 信号管线断裂 — 死代码特征 [HIGH]
**影响**: +5-10% 胜率

| # | 缺口 | 位置 | 修复 |
|---|------|------|------|
| 5a | `consolidate_signals()` 从未调用 | engine.py:150-156 | 在 flush_signals 和 _process_signal 之间插入分组+合并 |
| 5b | `strategy_hit_rates` 从未传入 | engine.py:54 | 从回测/实盘结果填充并传入 |
| 5c | `strategy_risk_budgets` 从未传入 | engine.py:54 | 在 RiskEngine 构造时传入 |
| 5d | `strategy_win_rates` 从未传入 | engine.py:208 | 在 size() 调用时传入 |
| 5e | Position 模型无 strategy_id | models.py:77-94 | 添加 `strategy_id: str = ''` |
| 5f | 等权 1/N 分配 | engine.py:91 | 改为按 Sharpe/win_rate 加权分配 |
| 5g | `_check_strategy_budget` 汇总所有仓位 | risk_engine.py:106-108 | 按 strategy_id 过滤 |

### P6: YAML-Code 参数映射断裂 [HIGH]
**影响**: +2-7% 胜率

所有 6 个策略受影响 — YAML 配置值从未被代码读取：

| 策略 | YAML key | Code key | YAML值 | Code默认 | 差距 |
|------|----------|----------|--------|---------|------|
| trend_following | take_profit_pct | profit_take_pct | 0.15 | 0.10 | 1.5x |
| trend_following | trailing_stop_atr_multiplier | trailing_stop_atr_mult | 1.5 | 3.0 | 2x |
| volatility_breakout | take_profit_pct | profit_take_pct | 0.10 | 0.05 | 2x |
| volatility_breakout | trailing_stop_atr_multiplier | trailing_stop_atr_mult | 2.0 | 2.5 | 1.25x |
| mean_reversion | take_profit_pct | profit_take_pct | 0.05 | 0.03 | 1.7x |
| funding_rate | take_profit_pct | profit_take_pct | 0.06 | 0.02 | 3x |
| momentum_rotation | take_profit_pct | profit_take_pct | 0.08 | 0.04 | 2x |

**修复**：在 `__init__` 中添加别名：`p.get('take_profit_pct', p.get('profit_take_pct', default))`

**stop_loss_pct** 在 YAML 中定义但从未被任何策略的 `generate_signals()` 读取（仅 momentum_rotation.py:37 使用）。

### P7: 校准问题 — 条件计数 + 信号强度 [MEDIUM]
**影响**: +3-8% 胜率

| # | 问题 | 修复 |
|---|------|------|
| 7a | 信号强度硬编码 (0.7-0.8)，condition count 未映射 | `strength = conditions_met / total_conditions` |
| 7b | mean_reversion vol_threshold=0.8 近乎恒 True | 默认值改为 1.2（匹配 YAML） |
| 7c | vol_breakout min_conditions=5 需全部满足 | 降为 3（任何 3/5 条件即可） |
| 7d | RSI-adaptive 用全局均值 (dead code) | 改为 per-entry RSI |
| 7e | exit 条件要求 vol_ok（应比 entry 宽松） | 从 exit 条件中移除 vol_ok |
| 7f | trend_following exit 用 Direction.SHORT 而非 FLAT | 改为 Direction.FLAT |

---

## 其他发现（未入前 7 但重要）

| ID | 问题 | 影响 |
|----|------|------|
| ISS-10 | volatility_breakout 始终发出 Direction.LONG | SHORT 信号丢失 |
| ISS-11 | trend_following exit 用 Direction.SHORT 而非 FLAT | 退出开新空头 |
| ISS-14 | BacktestEngine 出场时序错位 (1 bar lag) | -2-4% 胜率 |
| ISS-15 | signal_quality hit_rate 用 1-bar proxy | 验证虚高 5-10% |
| ISS-3 | BacktestEngine long-only | SHORT 侧改进不可测量 |

---

## 实施路线图

### Phase 1: 止盈止损方向感知 [1-2天]
1. `_runtime.py:profit_target_exit()` 添加 direction 参数
2. `mean_reversion.py` 拆分 long_entries/short_entries
3. Trailing stop: LONG 跟踪 highest HIGH, SHORT 跟踪 lowest LOW
4. 所有策略 `on_bar()` 添加 direction-aware profit_target + max_holding

### Phase 2: YAML-Code 桥接 + 校准 [1天]
1. 所有策略 `__init__` 添加 key 别名
2. volume_threshold 默认值 0.8 → 1.2
3. vol_breakout min_conditions 5 → 3
4. Trailing stop ATR mult 使用 YAML 值

### Phase 3: 信号管线修复 [2天]
1. `engine.py` 插入 `consolidate_signals()`
2. Position 模型添加 strategy_id
3. 传入 strategy_risk_budgets / strategy_win_rates / strategy_hit_rates
4. Condition count → signal strength 映射

### Phase 4: Regime 检测 [2天]
1. 实现 MarketRegimeDetector (ADX + BB width + ATR percentile)
2. engine.py on_bar() 中计算 regime
3. 策略门控：trend_following 需要 ADX>25, mean_reversion 需要 ADX<25
4. Wire MTFAligner 作为高时间帧确认

### Phase 5: BacktestEngine SHORT 支持 [1-2天]
1. Short position tracking with signed quantity
2. Direction-aware P&L calculation
3. Exit timing: same-bar-close option for profit_target fills

---

## 胜率提升估算

| Phase | 修复内容 | 预计提升 |
|-------|---------|---------|
| P1 | on_bar() 出场机制 | +10-20% |
| P2 | profit_target SHORT 支持 | +8-15% |
| P3 | Regime 检测 | +8-15% |
| P4 | Trailing stop 方向感知 | +5-12% |
| P5 | 信号管线修复 | +5-10% |
| P6 | YAML-Code 桥接 | +2-7% |
| P7 | 校准修复 | +3-8% |
| **去重合计** | | **+25-45%** |

注：各集群影响有重叠（如 P1 和 P2 共享 SHORT 侧修复），去重后合计估计 +25-45%。

---

## 数据来源

- 迭代 1: ANT-1-1, ANT-1-2, ANT-1-3, ANT-1-4
- 迭代 2: ANT-2-1, ANT-2-2, ANT-2-3, ANT-2-4
- 迭代 3: ANT-3-1, ANT-3-2, ANT-3-3, ANT-3-4
- 21 个 issue 记录在 wisdom/issues.md
- 3 轮决策记录在 wisdom/decisions.md
- 交叉学习记录在 wisdom/learnings.md
