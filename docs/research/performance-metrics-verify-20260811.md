# Performance metrics verification — 2026-08-11

**Purpose**: 用本地市场数据（parquet）+ 虚拟组合 / paper replay / 研究向量化路径，核验交易系统**可报告性能指标**（非 live）。  
**Session**: `20260811-perf-metrics-20260811-120059`  
**Version**: v0.7.0 · **HEAD**: see `main`

## Path semantics（必须先读）

| 路径 | 语义 | 可否宣称 live 一致 |
|------|------|-------------------|
| `multi_symbol_replay` / Baseline-0 | **paper_replay 虚拟账本**（事件路径，fee/slip 显式） | **≠ live**；parity 仅 paper↔live 抽象执行层 |
| Path A beta-overlay / Path B TPSL / dual-path / path_b_oos | **vectorized research** | `promotion_eligible=false`；**不**伪造 paper_replay GO |
| 回测 `BacktestEngine` | 独立向量账本 | **不在** paper/live parity 范围 |

**合同窗**: 2021-01-01 → 2026-08-04 · **48985** 根 1h bar · symbols BTC/ETH/SOL  
**成本默认**: fee=**0.1%** · slip=**0.1%** · capital=100_000  
**数据指纹 (aggregate)**: `e4d2797070a49bc0`

本地产物（runtime，默认不提交）: `data/paper_replay/perf_verify/`

---

## 1. 组合 paper-replay 性能面板（虚拟盘）

命令:

```bash
set PYTHONUTF8=1
python scripts/multi_symbol_replay.py \
  --symbols BTC/USDT,ETH/USDT,SOL/USDT \
  --start 2021-01-01 --end 2026-08-04 \
  --fee 0.001 --slip 0.001 --capital 100000 \
  --out data/paper_replay/perf_verify/multi_symbol_replay.json
```

| Mode | return% | Sharpe (ann.) | maxDD% | orders | 可比性 |
|------|---------|---------------|--------|--------|--------|
| btc_only | **−11.81** | −0.528 | 14.12 | 515 | 单标对照 |
| equal (shared) | **+22.63** | 0.342 | 24.71 | 1539 | shared book |
| shared_cap | **+21.00** | 0.348 | 22.22 | 1541 | shared book |
| **shared_risk_parity** | **+5.14** | **0.244** | **8.50** | **1547** | **Baseline-0 主模式** |
| risk_parity (silo) | +226.87 | 0.355 | 9.03 | 1547 | **不可与 shared 1:1 比**（独立资金片） |

**结论**: 共享账本下，系统能稳定产出 ret / Sharpe / maxDD / orders；主候选 **shared_RP** 以更低回撤换取较低全窗收益，与锁定 B0 工件**数值一致**。

---

## 2. Baseline-0 锁定门控（WFO 复用）

全窗指标与本次 `multi_symbol_replay` **一致**（见 `data/paper_replay/baseline0/`）。

| Gate | 值 |
|------|-----|
| decision | **PAPER-GO** |
| primary_mode | shared_risk_parity |
| full ret / Sharpe / maxDD / orders | +5.14% / 0.244 / 8.50% / 1547 |
| OOS mean Sharpe | **0.727** |
| OOS cum ret | **+12.93%** |
| OOS mean maxDD | **2.55%** |
| OOS pos segments | **5/7** |

WFO 协议: train 24m / fwd 6m · 7 segments · fee/slip 0.1%。

---

## 3. Path A — BTC beta + overlay（研究向量化）

```bash
python scripts/run_btc_beta_overlay_eval.py \
  --overlay-weight 0.30 --fee 0.001 --slip 0.001 \
  --out data/paper_replay/perf_verify/beta_overlay_eval.json
```

| Sleeve | return% | maxDD% | Sharpe | vs BTC excess | gate |
|--------|---------|--------|--------|---------------|------|
| BTC HODL | +118.54 | 77.19 | 0.531 | — | — |
| **BETA_OVERLAY w=0.30 taker** | **+165.63** | 69.47 | **0.602** | **+47.09pp** | **PASS** |
| B0 shared_RP (artifact) | +5.14 | 8.50 | 0.244 | −113.4pp vs HODL | 不作 vs-HODL 主叙事 |

**成本矩阵（overlay）**

| tag | fee/slip | excess vs HODL | gate |
|-----|----------|----------------|------|
| zero | 0 / 0 | +70.03pp | PASS |
| maker_like | 2bp / 2bp | +65.29pp | PASS |
| taker | 10bp / 10bp | **+47.09pp** | PASS |

North star: **超额 vs BTC + 成本敏感**，不是 win-rate。

---

## 4. Path B — 离散 TPSL / multi-window OOS

### 4.1 Dual-path 全窗指标（vectorized）

| Path | excess vs BTC | maxDD% | 其它 | metrics gate | validation |
|------|---------------|--------|------|--------------|------------|
| Path A overlay | **+47.09pp** | 69.47 | — | PASS | n/a |
| Path B TPSL SL4/TP10 min_rr2.5 | **+3.98pp** | **21.13** | wr≈0.39 · payoff≈2.50 · n_trades=69 · sh≈0.85 | PASS | **NO-GO** (n_trials=10) |

`combined_score`:**无** · `promotion_eligible`:**false**

### 4.2 Path B multi-window OOS（6 窗）

| Field | Value |
|-------|--------|
| research_go | **GO_DISCUSS** |
| n_trials_accounted | **69** (underreported=false) |
| frac_beat_btc | **0.50** |
| median OOS excess | **+1.43pp** |
| median OOS maxDD | **8.65%** |
| execution_path | **vectorized** |
| cost_attachment | fee_slip rows=2 · funding_mode=assumption |

---

## 5. 系统能力 vs 策略优劣（分开说）

| 系统能力（验证通过） | 策略结论（诚实） |
|----------------------|------------------|
| 多标的共享账本 replay 指标闭环 | shared_RP **PAPER-GO** 但全窗收益温和 |
| 指纹 / fee·slip 显式 | silo RP 高收益**不可**当 shared 替代叙事 |
| Path A 超额与成本矩阵 | overlay 打赢 HODL，但 **DD 仍高** |
| Path B 防过拟合门（NO-GO / GO_DISCUSS） | 未伪造成 GO；可讨论不可直接晋级 |
| 晋级 fail-closed | research vectorized **不** promote |

---

## 6. 复现

```bash
set PYTHONUTF8=1
python scripts/multi_symbol_replay.py --out data/paper_replay/perf_verify/multi_symbol_replay.json
python scripts/run_btc_beta_overlay_eval.py --out data/paper_replay/perf_verify/beta_overlay_eval.json
python scripts/run_dual_path_research_os.py --out data/paper_replay/perf_verify/dual_path.json
python scripts/run_path_b_oos.py --n-windows 6 --out data/paper_replay/perf_verify/path_b_oos.json
```

锁定 B0 对照: `data/paper_replay/baseline0/` · `docs/research/Candidate-Baseline-0-results.md`

---

## 7. 非范围

- Live 下单 / promote_to_live  
- 伪造 paper 样本门（T023 仍 **4/7**）  
- 宣称 backtest ≡ paper ≡ live  
- 合并 Path A+B 成单一 score

---

## 8. Re-verification

**UTC**: 2026-08-11 13:26  
**HEAD**: `e172cae`  
**Result**: **CONFIRMED** — multi_symbol_replay / overlay / dual-path / path_b_oos / B0 gate 数值与 §1–§4 一致；B0 full-window **exact match** (`shared_RP +5.143%`); promotion_eligible=false; no combined_score; silo RP not marketed as shared.

Runtime panel: `data/paper_replay/perf_verify/performance_panel.json` (gitignored).
