# Swarm Result — 提升量化策略胜率 (Win Rate)

## Best Solution

**Path**: backtest_validation → exit_rule_early_exit → trend_entry_filter → vol_breakout_entry_filter → mean_rev_entry_filter
**Verified Score**: 0.352
**Iteration**: 3 of 3
**Ant**: ANT-3-3

### Summary

ANT-3-3 提出一套覆盖 4 个阶段的胜率提升方案，直击系统三大架构缺陷：(1) 缺少止盈出场机制——所有模板只有趋势反转退出，没有 profit target；(2) 入场逻辑过度严格——三策略均使用 AND 全条件满足，实际触发率低；(3) 验证管道以 Sharpe 为唯一目标——`gate.py:41` 默认 `optimize_objective="sharpe"`，`optimizer.py:160-169` 无 `win_rate` 分支。方案预估将胜率从 ~40-50% 提升至 55-65%。

### Evidence Chain

- `gate.py:41` — `optimize_objective: str = "sharpe"` 验证管道无视 win_rate，优化方向偏差
- `optimizer.py:160-169` — `_objective_value()` 仅支持 sharpe/sortino/calmar/return，缺少 `win_rate` 分支
- `trend_following.py:239` — `entries = trend_up & rsi_ok_long & vol_ok & atr_ok` 四条件 AND，任一不满足即拒绝入场
- `volatility_breakout.py:199-205` — `atr_spike and bb_expanding and close > bb_upper and vol_surge and previous_squeeze` 五条件 AND
- `mean_reversion.py:129-131` — `entries = vol_ok & ((rsi<oversold & close<bb_lower) | (rsi>overbought & close>bb_upper))` 三条件隐式 AND
- `mean_reversion.py:100-103` — 出场条件 `close > bb_middle`，中线即退出导致频繁 whipsaw
- `backtest.py:35` — BacktestResult 已含 `win_rate` 字段，基础设施就绪，只需在优化器中启用

### Implementation Package

| Phase | 内容 | 关键改动 |
|-------|------|----------|
| P1 基础设施 | gate 加 win_rate 目标 + profit_target_exit() + param_space JSON | `optimizer.py` 1 行 + `gate.py` 默认值 + 新共享函数 |
| P2 入场放松 | AND → N-of-M (min_conditions) | 3 个模板行级改动 + RSI 参数范围扩大 |
| P3 出场改进 | 止盈接入 + trailing stop + 均值回归反向出场 | 6 模板 wiring + mean_reversion 出场逻辑 |
| P4 信号管线 | 强度加权整合 + 策略级风控预算 + 策略级 Kelly | `generator.py` + `RiskEngine` + `PositionSizer` |

## Why This Path Won

| Decision | Pheromone-guided? | Why it mattered |
|----------|-------------------|-----------------|
| start = backtest_validation | weighted (tau=2.86) | 根因定位：Sharpe-only 优化是胜率低的系统性原因，先修基础设施 |
| → exit_rule_early_exit | **yes** (tau=2.66, 最强边) | 止盈是胜率最直接杠杆——当前完全缺失 profit target |
| → trend_entry_filter | **yes** (tau=3.07→3.13) | trend_following 4-AND 最严格，放松后入场率提升最大 |
| → vol_breakout_entry_filter | NO (deviation, tau=0.09) | ANT-3-3 偏离 pheromone 提示，但证据链完整：5-AND 同样需放松 |
| → mean_rev_entry_filter | NO (deviation, tau=0.08) | 同上——覆盖三策略入场+出场，形成完整闭环 |

**关键洞察**：最佳路径的前两步跟随 pheromone（验证基础设施 + 止盈），后三步靠代码证据独立推理覆盖全部策略模板。Pheromone 指向核心问题，evidence 扩展到完整解法——两者互补。

## Runner-Up Solutions

| Rank | Ant | Path | Score | Diff | 败因分析 |
|------|-----|------|-------|------|----------|
| 2 | ANT-3-2 | rsi_tuning → trend_entry → early_exit → consolidation → multi_combination | 0.335 | -0.017 | RSI 阈值微调是局部优化，不如系统性修改入口逻辑；整合管线缺少 vol_breakout 覆盖 |
| 3 | ANT-2-4 | backtest_validation → early_exit → trend_entry → mean_rev_entry → param_search | 0.332 | -0.020 | 缺少 vol_breakout 入场放松；param_search 节点贡献模糊 |
| 4 | ANT-3-1 | macd_threshold → param_search → trend_entry → early_exit → backtest_validation | 0.319 | -0.033 | MACD 微调优先级错误；未覆盖 mean_reversion 出场缺陷 |
| 5 | ANT-3-4 | rsi_tuning → early_exit → trend_entry → consolidation → risk_filter | 0.315 | -0.037 | 缺少 vol_breakout 和 mean_reversion 出场改进 |

**稳定性判断**：Top 3 方案均包含 backtest_validation + early_exit + trend_entry 核心三角，分差仅 0.02，说明核心方向共识强。#1 领先靠全面覆盖三策略模板。

## Convergence Story

**Iterations**: 3 of 3 max
**Trigger**: max_iterations (非 stagnation)

| Iter | Entropy | tau_max | tau_mean | 状态 |
|------|---------|---------|----------|------|
| 1 | 6.475 | 1.72 | 0.874 | 广泛探索，14 节点全覆盖 |
| 2 | 6.435 | 2.04 | 0.767 | 聚焦初现，backtest_validation + early_exit 信号加强 |
| 3 | 6.332 | 3.13 | 0.687 | 最佳路径涌现，但 entropy 仍高（6.3/ln14≈6.3 为近均匀） |

**Interpretation**: Entropy 始终接近均匀分布上界（ln14≈2.64 的纯图 entropy 不同——此为边空间 91 条边的 Shannon entropy），说明 3 轮迭代不足以让 pheromone 充分收敛。但核心边（backtest_validation → early_exit → trend_entry）的 tau 已显著高于均值（3.13 vs 0.69），方向信号明确。建议如有后续可追加 2 轮以确认收敛。

## Cross-Iteration Consensus

12 只蚂蚁跨 3 轮迭代一致识别 3 个架构缺陷：
1. **无止盈出场** (11/12 ants 访问 exit_rule_early_exit)
2. **AND 入场过严** (9/12 ants 访问 trend_entry_filter)
3. **Sharpe-only 验证** (8/12 ants 访问 backtest_validation)

此共识度 >70%，远超随机期望（14 节点 5 步路径的期望覆盖率 ~36%），说明结果具有统计显著性。

## Caveats

- **Self-score discount**: 所有 verified_score = self_score × 0.5，无外部验证器——分数仅反映方案自评置信度，非真实胜率提升量
- **Evidence 为单源引用**: 每条证据仅引用一处代码行，未经多源交叉验证
- **搜索空间偏小**: 14 节点 × 5 步路径，更丰富的节点空间（如 time-frame 选择、止损策略细分）可能产出更优解
- **胜率预估范围宽**: 40-50% → 55-65% 为估计值，需回测验证
- **win_rate 与 profit_factor 权衡**: 方案自身警告——过度优化胜率可能损害盈亏比，应双目标跟踪

## Reproducibility

- **Config**: `.workflow/.team/TS-winrate-20260613/swarm-config.json`
- **Best path**: `.workflow/.team/TS-winrate-20260613/best.json`
- **Full trails**: `.workflow/.team/TS-winrate-20260613/trails/{1,2,3}.jsonl`
- **Best ant artifact**: `.workflow/.team/TS-winrate-20260613/artifacts/ant-3-3.json`
- **ACO params**: α=1.0, β=2.0, ρ=0.2, q=1.0, τ_init=1.0, 4 ants/iter
