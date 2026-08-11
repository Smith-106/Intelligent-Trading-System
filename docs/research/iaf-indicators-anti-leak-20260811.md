# IAF — 扩展技术指标 + 防未来函数 / 降过拟合

**Date**: 2026-08-11  
**Maestro session**: `indicator-anti-leak-20260811-20260811-063924`  
**Related**: [w17-antifuture-and-factors.md](./w17-antifuture-and-factors.md)

---

## 1. 目标

1. **引入更多正交技术指标**，拓宽研究因子面（避免只在 RSI/MACD 上反复拟合）  
2. **加固未来函数防护**：因果截断单测 + 负向 `shift` AST 扫描接入 `validate --method lookahead`

---

## 2. 新指标（`quantflow/indicators/oscillators.py`）

| 列名 | 含义 | 用途（降过拟合角度） |
|------|------|----------------------|
| `cci_20` | Commodity Channel Index | 偏离均价；与 RSI 相关但非线性不同 |
| `roc_12` / `mom_10` | 变化率 / 动量差 | 简单可解释，少参数 |
| `aroon_up/down/osc` | Aroon | 趋势年龄 vs 强度（ADX 互补） |
| `cmf_20` | Chaikin Money Flow | 价量资金流，异于 OBV/MFI |
| `realized_vol_20` | 已实现波动（年化） | 风险/仓位表面，非方向信号 |
| `bb_width_20` / `percent_b_20` | 带宽 / %B | 挤压与位置，配合 BB 带 |
| `trix_15` | 三重 EMA 变化率 | 平滑趋势，低噪声 |
| `tsi` | True Strength Index | 双平滑动量，抗抖 |

全部为 **trailing window / ewm(adjust=False)**，无中心窗、无负向 shift。

已接入 `IndicatorEngine.batch_calculate` 与 `compute_all` 子集路径；列入 `CLASSICAL_EXTENDED_NAMES`。

---

## 3. 防未来函数

| 机制 | 位置 |
|------|------|
| `shift_for_trade` | `indicators/causal.py` — 决策序列标准滞后 |
| `assert_series_causal` / `assert_frame_causal` | 截断前缀不变性（泄漏会改历史值） |
| `scan_source_for_negative_shift` | AST 抓 `shift(-n)` |
| `scan_strategy` 增强 | `validation/lookahead.py` 在 mask-agg 之外扫描负向 shift |

**原则**（与 W17 一致）：门禁与测试比再堆参数更值钱；新因子默认走因果单测模板。

---

## 4. 与「降低过拟合」的关系

- **更多指标 ≠ 自动更少过拟合**。价值在于：  
  - 研究时可做 **正交筛选 / 相关剪枝 / CPCV**，而不是在同一族指标上调参；  
  - `realized_vol` 等用于 **风险缩放** 而非再挖 α，减少「方向信号过拟合」压力。  
- 仍须：purged CV、成本矩阵、vs-BTC 产品门、paper 证据。

---

## 5. 测试

```bash
python -m pytest tests/unit/test_causal_oscillators.py \
  tests/unit/test_indicators.py \
  tests/unit/test_lookahead_scanner.py -q
# → 34 passed
```

---

## 6. 复现 / CLI

```bash
# 策略静态未来函数扫描（含负向 shift）
quantflow validate --strategy trend_following --method lookahead

# 特征侧仍走 FeatureStore end=timestamp（既有 PIT）
```

---

## 7. 未做（诚实边界）

- 未把新指标硬编码进 B0/B3–B5 冻结合同  
- 未默认打开 `book_risk_budget` 或 live  
- 未宣称新指标单独产生可交易 α  

---

## 8. 一句话

> **IAF：12 个正交振荡/波动因子进 Engine；因果单测 + 负向 shift 扫描补强未来函数门禁，为后续降过拟合筛选提供更干净的因子表面。**
