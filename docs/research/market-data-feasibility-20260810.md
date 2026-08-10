# 市场数据回测可行性验证 — 2026-08-10

**目的**: 用本地真实市场数据复现 Baseline-0，验证交易系统（研究路径）在成本后是否仍具备 paper 可行性。  
**命令**: `python scripts/run_baseline0.py`（full + WFO + cost grid + funding_tca）  
**ran_at**: 2026-08-10T13:46:15Z  
**pin**: `2021-01-01 → 2026-08-04` · `data_fingerprint.aggregate=e4d2797070a49bc0`  
**标的**: BTC/USDT, ETH/USDT, SOL/USDT · 1h · fee=0.001 · slip=0.001 · gate=nested  
**本地产物**（gitignore）: `data/paper_replay/baseline0/*` · 日志 `data/paper_sessions/b0_feasibility_run_20260810.log`

---

## 1. 一句话裁决

| 问题 | 答案 |
|------|------|
| 系统能否在真实历史上跑通研究闭环？ | **能** — full / WFO / cost grid / funding_tca 全绿退出 |
| Baseline-0 是否仍 **PAPER-GO**？ | **是** — 五门 checks 全 true |
| 这是否等于 live 可上？ | **否** — 仍差 T023 墙钟 + T024 真实 paper evidence；live 非默认验收 |
| 成本是否吃掉 alpha？ | **会** — 零成本 vs 生产费滑 drag **≈20.9pp**（BTC 1h reframe）；必须双报 |
| funding 挑战者（B3–B5）？ | 已密封 **KEEP_B0**；本次不重开 |

---

## 2. 数据前提

| 符号 | 本地 bars（全库） | 合同窗 bars（pin） | 备注 |
|------|------------------:|-------------------:|------|
| BTC/USDT | ~384k | 48985 | 合同窗对齐 |
| ETH/USDT | ~67k | 48985 | 合同窗对齐 |
| SOL/USDT | ~49k | 48985 | 合同窗对齐 |
| 新鲜度（跑前） | age ≈ 1.4h | — | 足够研究复现 |

Fingerprint 三标的均 `bar_count=48985`，aggregate **`e4d2797070a49bc0`**（与历史 B0 pin 一致）。

---

## 3. Gate 结果（研究门）

**decision: `PAPER-GO`**

| Check | 结果 |
|-------|------|
| oos_mean_sharpe_gt_0 | ✅ |
| oos_cum_return_ge_0 | ✅ |
| oos_mean_dd_le_equal | ✅ |
| pos_segments_ge_half | ✅ (5/7) |
| full_orders_gt_0 | ✅ |

### 主模式 `shared_risk_parity`（B0 合同主路径）

| 指标 | 值 |
|------|-----|
| Full-window return | **+5.14%** |
| Full-window max DD | **8.50%** |
| Full-window orders | **1547** |
| Full Sharpe（gate 字段） | 0.24 |
| WFO OOS mean Sharpe | **0.73** |
| WFO OOS cum return | **+12.93%** |
| WFO OOS mean max DD | **2.55%** |
| WFO pos segments | **5 / 7** |

### WFO 分段 OOS（shared RP 收益，%）

| 段 | 窗 | ret% | maxDD% | orders |
|----|-----|-----:|-------:|-------:|
| 0 | 2023-01→07 | +5.50 | 1.97 | 153 |
| 1 | 2023-07→2024-01 | +6.07 | 1.22 | 151 |
| 2 | 2024-01→07 | +2.08 | 2.27 | 173 |
| 3 | 2024-07→2025-01 | +4.28 | 1.51 | 141 |
| 4 | 2025-01→07 | **−1.93** | 3.13 | 126 |
| 5 | 2025-07→2026-01 | +0.95 | 2.65 | 133 |
| 6 | 2026-01→07 | **−4.23** | 5.10 | 120 |

→ 可行性 **不是**「每段都赚」；是 **多数段为正 + 成本后仍过门**。近两段偏弱，需 paper 日课继续观察。

### 全窗多模式对照（同 pin，fee/slip=0.001）

| 模式 | return% | maxDD% | orders | 备注 |
|------|--------:|-------:|-------:|------|
| equal | +22.6 | 24.7 | 1539 | 回撤大 |
| shared_cap | +21.0 | 22.2 | 1541 | 回撤大 |
| **shared_risk_parity** | **+5.14** | **8.50** | 1547 | **B0 主路径** |
| risk_parity | +226.9 | 9.03 | 1547 | winner_by_sharpe；**非** B0 晋级主模式 |
| btc_only | −11.8 | 14.1 | 515 | 单标的不支撑 B0 叙事 |

**解读**: 多标的 shared RP 是「可控回撤下的温和正期望」路径；极端 `risk_parity` 高收益 **不得**单独当作 GO 叙事（合同主模式是 shared RP）。

---

## 4. 成本保真（BTC 1h reframe + funding_tca）

### fee × slip 网格（20 cells，orders=714）

| fee | slip | ret% | Sharpe | maxDD% |
|----:|-----:|-----:|-------:|-------:|
| 0 | 0 | +40.00 | 1.03 | 6.97 |
| **0.001** | **0.001** | **+19.12** | **0.55** | **9.43** |
| 0.002 | 0.002 | +1.41 | 0.06 | 12.91 |

- **cost_drag**（零成本 − 生产）: **≈ +20.88 pp**  
- 生产格仍为正收益 → 支持「有成本后仍可研究 paper」  
- 高成本角几乎抹平 → **禁止零成本单报 GO**

### funding_tca（T014）

| 字段 | 值 |
|------|-----|
| mode | hybrid / measured |
| symbol_meta | BTC-USDT-SWAP |
| n_events | 270 |
| estimated annual drag | **≈ 4.84%** |
| rule | GO 叙事必须与 fee×slip **并列引用** |

### 风险消融

`research_bypass` 与 prod DD 档在本 reframe 上结果一致（ret≈19.12%），未见「关风控才赚钱」的假象。

---

## 5. 对「交易系统可行性」的分层结论

| 层级 | 结论 | 证据 |
|------|------|------|
| **L1 工程可运行** | ✅ | runner 全链路 exit 0；pin + fingerprint |
| **L2 研究经济性（B0）** | ✅ 有条件 | PAPER-GO；shared RP 成本后全窗/WFO 过门 |
| **L3 成本诚实** | ✅ 已嵌入 | 20-cell grid + funding_tca；drag 大 |
| **L4 挑战者多样性** | ⚠️ 已测 | B1–B5 **KEEP_B0** — 系统能拒绝坏信号 |
| **L5 paper 运营样本** | ❌ 未满 | T023 **3/7**；T024 真实 promote 未过 |
| **L6 live** | ⛔ 非本次范围 | 默认不做 |

**可行性定义（本报告）**:  
「在钉扎历史 + 真实 OHLCV + 费滑/funding 披露下，主研究合同能否复现 PAPER-GO，且管道 fail-closed。」  
→ **满足。**  
不等于：「现在可以无顾样本去 live。」

---

## 6. 风险与局限（必读）

1. **近端 WFO 两段为负** — 制度漂移可能；依赖 paper 连续日课而非只信历史 GO。  
2. **cost reframe 主格是 BTC-only** — multi-symbol 全窗另报；summary 中 ETH/SOL「~300 bars」是 reframe 侧注释，**不等于** multi_symbol 合同窗缺数（合同窗三标的各 48985）。  
3. **funding 序列窗口偏短**（hybrid）— 年化 drag 为估计，须并列披露。  
4. **parity 边界** — backtest/vectorized 与 paper/live 账本不完全同一路径；晋级证据应以 paper 为准。  
5. **B3–B5 KEEP** — funding 信号族未替代 B0；系统可行性 ≠ 每个策略都 GO。

---

## 7. 建议下一步（与 ops 对齐）

| 优先级 | 动作 |
|--------|------|
| P0 | 继续 T023 Path A 至 ≥7 日 → T024 真实 evidence |
| 研究 | 无需为「再证明一次」重开 W28；若疑近端失效，开 **独立合同** 做 regime 切片 |
| 不建议 | 用 risk_parity 全窗 +226% 对外宣传；用零成本 Sharpe 当 headline |

### 复现

```bash
export PYTHONUTF8=1
python scripts/run_baseline0.py
# 产物: data/paper_replay/baseline0/{gate,run_meta,multi_symbol_replay,wfo_shared_rp,cost_fidelity_report,funding_tca}.json
```

---

## 8. 变更日志

| 日期 | 说明 |
|------|------|
| 2026-08-10 | 全量 B0 复现；PAPER-GO；cost drag≈20.9pp；funding annual≈4.84% |

*研究 OS 可行性：通过。运营晋级：未完成。*
