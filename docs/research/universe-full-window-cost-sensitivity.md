# Shared-RP 全窗 fee×slip 成本敏感度（BTC/ETH/SOL）

**生成命令**

```bash
python scripts/universe_expand_pipeline.py \
  --symbols BTC/USDT,ETH/USDT,SOL/USDT \
  --cost-days 2045 \
  --out data/paper_replay/universe/full_window_cost_sensitivity.json
```

**原始 JSON**：`data/paper_replay/universe/full_window_cost_sensitivity.json`  
**合同对齐**：接近 Baseline-0 三币交集窗（SOL 自 2021-01 起）；路径为 **shared book + symbol-level RP**（`research_risk_bypass=True`，**无** nested 方向门）。  
**勿与** Path B `run_baseline0.py` / `gate.json` 的 nested 数字直接比。

## 数据 SLA

| Symbol | 1h bars | age | quality | SLA |
|--------|---------|-----|---------|-----|
| BTC/USDT | 66635 | ~8h | 1.00 | OK |
| ETH/USDT | 66635 | ~8h | 1.00 | OK |
| SOL/USDT | 49091 | ~8h | 1.00 | OK |

## 成本网格（全窗交集）

| 设定 | intersection bars | 说明 |
|------|-------------------|------|
| days≈2045（SOL 全可用跨度） | **49072** | 三币时间戳交集 |

| taker fee | slip | return % | Sharpe (ann.) | max DD % | orders |
|-----------|------|----------|---------------|----------|--------|
| 0.0 | 0.0 | **+30.52** | **1.12** | 6.03 | 3161 |
| 0.001 | 0.001 | **+2.90** | **0.14** | 9.33 | 3161 |
| 0.002 | 0.002 | **-18.80** | **-0.84** | 23.90 | 3161 |

- **cost_drag_pp（零成本 − 0.1%/0.1%）= 27.62 pp**
- 解读：在 shared-RP 全窗路径上，**名义收益对费滑极敏感**；零成本叙事会严重高估可晋级 alpha。
- 与既有 knowhow（单标的 classic 约 ~21 pp 拖累）**同方向**，组合路径拖累可更大。

## 结论（工程/研究）

1. **任何 GO / paper 晋级必须附 fee×slip 网格**（P0 cost_fidelity 已硬绑）。  
2. **0.2%/0.2%** 单元格用于压力：若生产更接近 taker 偏高，应看该格是否仍成立。  
3. 本报告 **不是** Baseline-0 PAPER-GO 复现（无 nested、非 WFO）；用途是 **组合扩展流水线的成本现实**。  
4. `default.yaml` 的 `portfolio_optimization.enabled` 仍应保持 **false**；研究/overlay 显式开启。

## 复现

```bash
python scripts/universe_expand_pipeline.py --symbols BTC/USDT,ETH/USDT,SOL/USDT --cost-days 2045
# 或短窗冒烟
python scripts/universe_expand_pipeline.py --symbols BTC/USDT,ETH/USDT,SOL/USDT --cost-days 90
```
