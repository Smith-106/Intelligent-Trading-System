# BTC 回测优化：降回撤 / 提超额（2026-08-11）

**Goal**: 继续回测市场，优化设计与参数，缩小回撤、扩大收益（相对 BTC HODL）  
**Maestro session**: `btc-dd-return-optimize-20260811-20260811-061046`  
**数据**: BTC/USDT 1h parquet pin `2021-01-01 → 2026-08-04`（48985 bars）  
**成本主报告**: taker fee=10bp + slip=10bp（仅 overlay 换手计费）

---

## 1. 基线（优化前固定默认）

| 路径 | Return | Excess vs HODL | maxDD | Sharpe | Gate |
|------|-------:|---------------:|------:|-------:|------|
| BTC HODL | +118.54% | 0 | 77.19% | 0.531 | — |
| **legacy** reduce_off w=**0.25** MA 96/400 | +158.97% | **+40.43 pp** | 70.86% | 0.590 | PASS |
| B0 shared RP（artifact） | +5.14% | −113.40 pp | ~8.5%* | — | FAIL product |

\*B0 DD 来自多标的研究基线，不可与纯 BTC 产品路径直接比「谁更赚钱」。

---

## 2. 做了什么

1. 复现 `scripts/run_btc_beta_overlay_eval.py` 基线  
2. 粗扫 weight/mode/MA（`--sweep`）  
3. 新脚本 `scripts/run_btc_overlay_dd_optimize.py`：网格 + **DD throttle / vol target / hysteresis** 设计杆  
4. **Holdout 切片**：IS 2021–2024 / OOS 2025+ / 2022 熊 / 2022-11 后  

产物（本地，gitignore 运行时）：

- `data/paper_replay/beta_overlay/baseline_eval.json`  
- `data/paper_replay/beta_overlay/dd_optimize_quick.json`（482 configs）  
- `data/paper_replay/beta_overlay/holdout_profiles.json`  

---

## 3. 选定配置

### Primary（新默认）— `primary_w30`

```text
mode=reduce_off  overlay_weight=0.30  fast=96  slow=400
dd_throttle=off  vol_target=off  hysteresis=off
```

| 窗 | Excess | maxDD | vs legacy |
|----|-------:|------:|-----------|
| Full pin | **+47.09 pp** | **69.47%** | excess **+6.66 pp**，DD **−1.39 pp** |
| IS 2021–2024 | +21.50 pp | 69.47% | 仍 beat |
| **OOS 2025→** | **+9.14 pp** | 45.14% | legacy +7.63 → 更好 |
| Post-2022 low | +14.63 pp | 45.14% | 更好 |
| Bear 2022 | +8.60 pp | 59.20% | 更好 |

Taker 成本矩阵（primary）：zero +70.0 / maker +65.3 / **taker +47.1** — 全 PASS。

### Defensive（可选，非默认）— `defensive_dd35`

```text
同上 + dd_throttle=0.35  dd_floor_scale=0.50
```

| 窗 | Excess | maxDD | 备注 |
|----|-------:|------:|------|
| Full | +23.99 pp | **66.47%** | DD 更好，超额牺牲大 |
| IS 2021–2024 | **−4.90 pp** | 66.47% | **未 beat HODL**（节流过早砍 beta） |
| OOS 2025 | +8.36 pp | 45.38% | 仍 beat |
| Bear 2022 | +9.77 pp | 57.98% | DD 最优档之一 |

→ 仅当「回撤优先于超额」时人工选用；**不**作 CLI 默认。

---

## 4. 设计结论（参数模型）

| 杠杆 | 结论 |
|------|------|
| `reduce_off` vs `add_on` | 本窗 **reduce_off** 在 taker 下超额更高、DD 更低 |
| overlay weight | **0.30** 优于 0.25（收益+DD 同向改善）；再高换手税上升 |
| MA 96/400 | 低换手仍主导；更长 MA 网格未稳定超越 |
| DD throttle | 能压 DD，但易在牛市 IS **输 HODL** → 默认关 |
| vol target / hysteresis | 本网格未击败 primary；保留代码杆供后用 |

---

## 5. 代码落地

| 项 | 变更 |
|----|------|
| `scripts/run_btc_beta_overlay_eval.py` | 默认 `--overlay-weight 0.30`；sweep 含 0.35 |
| `quantflow/cli/main.py` `eval-btc-overlay` | 默认 weight 0.30 |
| `BookRiskBudgetConfig.overlay_sleeve` / `default.yaml` | 0.20 → **0.30**（仍 `enabled: false`） |
| `quantflow/strategy/research/btc_overlay_profiles.py` | 命名配置 PRIMARY / LEGACY / DEFENSIVE |
| `scripts/run_btc_overlay_dd_optimize.py` | DD/vol/hysteresis 网格优化器 |
| 单测 | `tests/unit/test_btc_overlay_profiles.py` |

---

## 6. 复现命令

```bash
export PYTHONUTF8=1
# Primary（新默认，可省略 weight）
python scripts/run_btc_beta_overlay_eval.py --fee 0.001 --slip 0.001 \
  --mode reduce_off --fast 96 --slow 400 \
  --out data/paper_replay/beta_overlay/eval_primary.json

# 或 CLI
quantflow eval-btc-overlay --fee 0.001 --slip 0.001

# 网格（可选）
python scripts/run_btc_overlay_dd_optimize.py --quick \
  --out data/paper_replay/beta_overlay/dd_optimize_quick.json

# 单测
python -m pytest tests/unit/test_btc_overlay_profiles.py \
  tests/unit/test_benchmark_excess_book_budget.py \
  tests/unit/test_config.py -q
```

---

## 7. 诚实边界

- 参数在 pin 窗上成本感知选择；OOS 2025 仅作 **一致性检查**，非独立 α 证明  
- 未宣称 live 就绪（T023/T024 仍运营开放）  
- 未改 B0/B3–B5 冻结合同  
- KOL/Discord 旁路仍 DEFER  

---

## 8. 一句话

> **新 primary：reduce_off w=0.30 MA96/400 — 全窗超额 +47.1pp（较旧默认 +6.7pp），maxDD 69.5%（−1.4pp），OOS2025 仍 +9.1pp beat HODL；DD 节流仅作可选 defensive。**
