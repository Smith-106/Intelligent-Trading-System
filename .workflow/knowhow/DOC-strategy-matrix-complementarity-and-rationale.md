---
title: QuantFlow 策略矩阵与互补性 + 候选学术依据
category: strategy
createdBy: manage-harvest
sourceRef: brainstorm-20260602-new-strategies
---
## 来源
brainstorm 20260602-brainstorm-new-strategies（5 候选策略收敛）。收割时 4/5 已实现（momentum_rotation / volatility_breakout / funding_rate / ml_ensemble 模板已存在），仅跨交易所套利未实现。此条目记录代码注释未覆盖的增量：策略间互补性矩阵 + 学术依据。

## 当前策略矩阵

| 策略 | 类型 | 市场状态 | 相关性 |
|------|------|----------|--------|
| Trend Following | 趋势（时间序列动量） | 趋势市 | 基线 |
| Mean Reversion | 均值回归 | 震荡市 | 低 |
| Elliott Wave | 波浪 | 全状态 | 中 |
| Momentum Rotation | 横截面动量 | 趋势市（牛市轮动） | 与趋势跟踪低相关——TS 动量 vs 横截面动量 |
| Volatility Breakout | 波动率状态转换 | 盘整→突破 | 低——捕捉波动率转换非价格方向 |
| Funding Rate | Crypto 特有均值回归 | 震荡市 | 低——费率信号与传统技术指标无关 |
| ML Ensemble | 非线性因子组合 | 全状态 | 与所有规则策略低相关 |
| Cross-Exchange Arbitrage（未实现） | 统计套利/市场中性 | 全状态 | 负相关——不依赖方向 |

## 互补性设计原则
策略组合以低/负相关为优先：时间序列动量（Trend）+ 横截面动量（Rotation）+ 均值回归（MR/Funding）+ 波动率转换（VolBreak）+ 非线性组合（ML）+ 市场中性（Arb，待实现）覆盖不同市场状态与信号维度，降低组合回撤。

## 学术依据
- Momentum Rotation: Jegadeesh & Titman (1993) 动量效应
- Volatility Breakout: TTM Squeeze (Carter), BB Squeeze
- Cross-Exchange Arbitrage: Avellaneda & Lee (2010) 统计套利
- ML Ensemble: de Prado (2018) Advances in Financial ML（Meta-Labeling 过滤、Purged CV 防过拟合）

## 实施状态（2026-07-20）
P1 波动率突破 ✅ / P2 资金费率 ✅ / P3 动量轮动 ✅ / P4 ML集成 ✅ / P5 跨交易所套利 ☐（架构改动大，优先级最低，未实现）。实施顺序详见 spec architecture-constraints.md「新增策略实施顺序」。
