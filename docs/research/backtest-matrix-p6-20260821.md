# QuantFlow 交易数据回测报告 · P6（三模型共识执行）

日期：2026-08-21 ｜ 数据源：`*-BINANCE` 干净分区（v0.9.0 重跑，奇偶校验过）｜ 引擎：内置向量化 BacktestEngine

## 执行摘要

首次对干净 Binance 归档数据完成系统性回测矩阵：**12 cell 基线 + 2 单元贝叶斯优化 + 完整 GO/NO-GO 门**。
结论：默认参数下 1h 高频信号被交易成本主导（全线负 Sharpe）；唯一亮点 ETH 1d trend_following
（基线 Sharpe 0.66 / +344%）经优化提升至 1.04 后，**被防过拟合门诚实拒绝（PBO=0.714 ≥ 0.5 → NO-GO）**。
零晋升、B0/B3–B5 冻结未触碰，`promotion_eligible` 恒 false。

## 方法（三模型共识设计）

deepseek-v4-flash / ox-alpha-free / hy3 独立设计后 root 交叉裁决：
显式 `-BINANCE` 后缀输入（否决 resolve 接线防静默换源）；CLI 补 `--timeframe` 过滤（修复混 TF 无效结果缺陷）；
GATE/RESEARCH 分层；holdout 2026-07 锁箱不解封；fee=0.001 主口径；静态前瞻扫描先行。

## R0 数据体检（全过）

| 分区 | TF | 行数 | 时间戳唯一 |
|---|---|---|---|
| BTC_USDT-BINANCE | 1h / 1d | 66,397 / 2,769 | ✅ |
| ETH_USDT-BINANCE | 1h / 1d | 66,397 / 2,769（本轮补齐） | ✅ |
| SOL_USDT-BINANCE | 1h | 48,898 | ✅ |
| XRP_USDT-BINANCE | 1h | 22,632 | ✅ |

## R1 基线矩阵（默认参数，fee=0.001，trainval 止 2026-06-30）

| Cell | Sharpe | Return | MaxDD | Trades | Win% |
|---|---|---|---|---|---|
| TF BTC 1h (2021→) | -0.822 | -79% | -82% | 1021 | 35.8 |
| TF ETH 1h | -0.202 | -69% | -86% | 1354 | 37.7 |
| TF SOL 1h | -0.185 | -76% | -91% | 1038 | 40.1 |
| MR BTC 1h | -5.729 | -100% | -100% | 4433 | 33.0 |
| MR ETH 1h | -4.017 | -100% | -100% | 6080 | 36.9 |
| MR SOL 1h | -2.618 | -100% | -100% | 4422 | 41.3 |
| **TF BTC 1d** | -0.071 | -39% | -72% | 65 | 47.7 |
| **TF ETH 1d** | **+0.662** | **+344%** | -76% | 73 | 52.1 |
| MR BTC 1d | -0.282 | -61% | -71% | 247 | 47.8 |
| MR ETH 1d | +0.037 | -49% | -67% | 227 | 50.7 |
| TF XRP 1h (RESEARCH) | +0.384 | +21% | -50% | 455 | 36.5 |
| MR XRP 1h (RESEARCH) | -3.661 | -98% | -98% | 1992 | 38.5 |

全部通过 num_trades 验收（≥30/≥50）。

## R2 静态扫描（6 项全绿）

lookahead / causal_preflight / recursive × 两策略：无掩蔽聚合泄漏、无高severity因果违规、无循环依赖。

## Optimize + Gate

| 单元 | 默认 Sharpe | 优化后 | Gate 判定 |
|---|---|---|---|
| ETH 1d TF | 0.662 | **1.04**（fast=3/slow=30-38/ATR=3.0） | **NO-GO**：CPCV PBO=0.714 ≥ 0.5；OOS eff 0.42；WFO 窗间波动 0.75–1.43 |
| BTC 1h TF | -0.822 | -0.110 | 未进 gate（优化无法转正，成本主导） |

信号质量（ETH 1d gate）：precision=0.532 / recall=0.045 / brier=0.511 —— 方向略优于随机但召回极低，
不足以支撑可交易边际。

## 关键发现

1. **成本主导 1h**：MR 策略 1h 约 800–1100 笔/年，单边 0.1% fee 下年成本摩擦 >30%，任何未过滤信号必然亏损；
   与 F6（向量化不含 ADX regime gate）叠加，1h 数字为"上限估计中的下限样本"。
2. **日线趋势跟随是本数据集上唯一正期望区**：ETH 1d TF 在牛熊完整周期（2019–2026）正收益，
   但 CPCV 判定其参数选择过拟合（PBO 71%）——**方向有信号、参数不稳**，符合"趋势 beta 存在、alpha 调参脆弱"的行业常识。
3. **门禁体系工作正常**：optimize 的 in-sample 改善未能骗过 CPCV/WFO，fail-closed 行为符合设计预期。
4. **XRP 短历史**（2.5 年）：trend_following 正 Sharpe 但样本不足进 gate，保留 RESEARCH tier 观察。

## 与 Baseline-0 的关系（只观察不推翻）

层级不同（组合级 shared-RP paper 合同 vs 单策略研究网格），禁止 equity 直接互比。
方向性观察：BTC 1h 2021→ 窗口 trend_following 向量化负 Sharpe 与 B0 强调 regime gate 必要性的立场一致。

## 后续建议

1. ETH 1d TF 的**固定经典参数**（非优化）做 WFO 前向观察——检验"方向存在、参数敏感"假设；
2. 1h 层引入 regime gate 后重跑（需 on_bar 路径 paper-replay，非本轮向量化范围）；
3. mean_reversion 需重设成本模型（maker 挂单假设）后再评估，当前 taker 口径下无研究价值；
4. holdout 2026-07 保持锁箱，待候选策略定型后一次性解封。

---
*产物：`data/research_matrix/r1_results.txt`；冻结不变量全程未触碰；promotion_eligible=false。*
