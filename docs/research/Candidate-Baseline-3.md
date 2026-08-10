# Candidate Baseline-3 — Funding-rate family (signal A/B)

**Status**: **FROZEN KEEP_BASELINE_0**（T027）— confirmed by **W15 denser re-run** (still 0 trades @ thr)  
**Task**: T025 contract · T026 runner · **T027 freeze** · W15 re-run `20260810_w15/`  
**Date**: 2026-08-09  
**Against**: [Baseline-0](./Candidate-Baseline-0.md)（唯一 **PAPER-GO**）  
**Runner**: `python scripts/run_baseline3_challenger.py`  
**Artifacts**: `data/paper_replay/baseline3/` (T026) + **`baseline3/20260810_w15/`** (W15; no overwrite)  
  (`funding_wfo.json`, `fee_slip_grid.json`, `funding_tca.json`, `adjudication.json`, `run_meta.json`, **`adjudication_frozen.json`**)

**W15 note**: merged funding n=315 (was 63); max \|rate\|=0.0005 still &lt; 0.001 → 0 orders; verdict remains KEEP. See [baseline3-w15-rerun.md](./baseline3-w15-rerun.md).

---

## 1. Why this is “fourth” and complementary

| Contract | Signal logic | Role |
|----------|--------------|------|
| **B0** | classic `trend_following` + multi-symbol shared RP | **Promoted** paper candidate |
| **B1** | non-MA channel/mom (donchian / volume_roc / rsi_thrust) | Frozen **KEEP B0** |
| **B2** | mean_reversion + volatility_breakout | Frozen **KEEP B0** |
| **B3（本文件）** | **`funding_rate`（funding 极值 + OI 确认）** | **Crypto-native / meta 路径** — 与价格趋势结构正交 |

### 明确不是什么

- **不是** B1/B2 换皮。禁止 donchian / RSI+BB / vol-breakout 作为 B3 主族。  
- **不是** 多标的 shared-RP 升级尝试（那是 B0 书；B3 默认 **BTC-only nested 信号 A/B**，与 B1/B2 协议对齐，便于 Wave-C 对照）。  
- **不是** Optuna 搜参晋级。  
- **不是** 零成本 Sharpe 海报。

### 为何默认 `funding_rate`

1. B2 合同已写明 funding 因 bar 路径未注入而 **defer**；T014 后 `funding_tca` 已进 GO/register 合同。  
2. 策略实现已存在：`quantflow/strategy/templates/funding_rate.py` + catalog 注册（T018）。  
3. 与 classic 趋势门 **逻辑正交**（拥挤度/资金费率均值回归，而非 MA/通道）。  
4. 数据：`meta_funding_rate` / OI 历史可经 `DataStore` / `funding_tca_report` 路径获取；**若无法对齐到 1h bar，本实验直接 NO-GO 记录原因，不算升级失败政治**。

**备选族**（仅当 T025 修订合同并改 status 时启用；默认不跑）：

| 备选 | 何时考虑 |
|------|----------|
| `momentum_rotation` | funding 数据不可用且需横截面故事 |
| `elliott_wave` / `ml_ensemble` 固定参 | 研究兴趣；**更高过拟合风险**，须额外 NO-GO 纪律 |

---

## 2. Experiment contract（本基线不可变，直至正式 supersede）

| Field | Locked value |
|-------|----------------|
| Strategy family | **`funding_rate`**（YAML: `quantflow/config/strategies/funding_rate.yaml`） |
| Control | `trend_following` classic（同窗同成本 nested） |
| Direction gate | **`nested`**（与 B1/B2 一致） |
| Book | **BTC-only** paper_replay 信号 A/B（多标的 RP **不**作为 B3 晋级条件） |
| Timeframe | `1h` |
| Window pin | `2021-01-01` → `2026-08-04`（T011；与 B0/B1/B2 相同） |
| WFO | train **24** m / forward **6** m；**OOS-only** 主指标 |
| Costs (production quote) | **0.1% fee + 0.1% slip** |
| Cost grid | 至少 `0/0`、`0.1%/0.1%`、`0.2%/0.2%`（暴露 fee-drag 陷阱） |
| Funding/TCA | **必写** `funding_tca` 块（T014）；mode 允许 `assumption` / `measured` / `hybrid` |
| Meta bars | 信号 bar 必须含可用 `funding_rate`（及 OI 若策略启用确认）；缺失 → 实验 **BLOCKED/NO-GO** 并写原因 |
| Optuna | **Forbidden** for promotion |
| Capital | `100_000` quote（对照用） |
| research_risk_bypass | 允许与 B1/B2 相同（隔离信号；**成本仍施加**） |

### 固定参数（禁止搜参晋级；来自默认 YAML / 策略默认）

| Param | Default (contract) |
|-------|--------------------|
| `entry_threshold` | `0.001` |
| `exit_threshold` | `0.0003` |
| `oi_lookback` | `3` |
| `oi_change_threshold` | `0.05` |
| 其他 | 以 `funding_rate.yaml` / 类默认为准；变更必须升合同版本 |

---

## 3. Upgrade rule（继承 Wave-C / B1 / B2）

仅当 **同时** 满足才可写 **UPGRADE**（否则 **KEEP_BASELINE_0** 或 **REJECT** 作研究记录）：

1. OOS **mean Sharpe > 0**  
2. OOS mean Sharpe **≥ classic 对照**（同 pin 窗、同 nested、同 0.1%/0.1%）  
3. DD 纪律：不显著劣于对照（沿用 B1 文档：mean maxDD 不恶化到不可接受；具体阈值在 T026 报告表给出对照列）  
4. 生产报价下 **orders/fills > 0**（非退化）  
5. Fee grid：不得仅在 **0/0** 好看；0.1% 仍须讲得通  
6. GO 叙事含 **funding_tca**（旁注年化拖累假设/实测），**不能**用 funding 代替 fee×slip  
7. **无 Optuna**、无泄漏窗、无换 pin 却不声明  

**预期先验**：KEEP B0 **是成功交付**。B3 的首要价值是 **正交负/正结果证据**，不是强行第二 PAPER-GO。

多标的 shared-RP **不**因 B3 信号 A/B 好就自动晋升；若未来要 shared-RP funding 书，须 **新合同版本**（不在本 T025 范围）。

---

## 4. Data & implementation gates（T026 开工前）

| Gate | Pass criteria |
|------|----------------|
| G1 Meta available | BTC（及对照所需）funding 历史可查询；长度覆盖 pin 窗或明确缩短窗 + 理由 |
| G2 Bar join | 1h OHLCV 与 funding/OI **可对齐** 供 `FundingRateStrategy.generate_signals` |
| G3 Runner | `run_baseline3_challenger.py` 写出 WFO + fee grid + funding_tca + adjudication + run_meta（T011 fingerprint） |
| G4 Cost law | register/GO 路径仍 fail-closed on cost + funding_tca（不为本实验放松） |

任一 G1–G2 失败：T026 产出 **BLOCKED** 报告即可关闭技术故事，**不要**用纯价格假 funding 造 GO。

---

## 5. Results（T026 — 2026-08-09）

**Data status**: `NARROWED` — local `meta_funding_rate` only covers **2024-01-01 → 2025-05-11** (63 events), not full pin 2021→2026-08-04.  
Effective bars ≈ 11905 @1h. WFO 24m/6m → **0 segments** → single **50/50 OOS fold** (documented degradation).  
**Signal density**: measured max \|funding\|=0.0005 **&lt; entry_threshold 0.001** → funding_rate produced **0 orders** under contract params (not a GO path).

| Label | Full ret% | Full Sh | Full maxDD% | OOS sum% | OOS meanSh | Orders |
|-------|-----------|---------|-------------|----------|------------|--------|
| classic (control) | +1.62 | 0.33 | 5.51 | +6.73 | **2.56** | 143 |
| funding_rate | 0.00 | n/a | 0.0 | 0.00 | n/a (−10 placeholder) | **0** |

### Fee×slip (effective window)

| Label | 0/0 | 0.1%/0.1% | 0.2%/0.2% |
|-------|-----|-----------|-----------|
| classic | +4.95 / 0.96 | **+1.62 / 0.33** | −1.60 / −0.30 |
| funding_rate | 0 / n/a | **0 / n/a** | 0 / n/a |

### funding_tca (quote)

| Field | Value |
|-------|--------|
| mode | hybrid (measured short series + assumption fallback fields) |
| measured | 63 events from `data/s3_verify/raw` BTC/USDT |
| notes | Full-pin re-run requires denser funding history; do not promote on this window alone |

---

## 6. Adjudication（**FROZEN T027**）

| Field | Value |
|-------|--------|
| **Verdict** | **KEEP_BASELINE_0** |
| upgrade | **false** |
| Frozen at | 2026-08-09 (T027) |
| Seal artifact | `data/paper_replay/baseline3/adjudication_frozen.json` |
| Best OOS meanSh (challenger) | n/a (0 trades) |
| Challenger OOS meanSh > 0 | **No** |
| ≥ classic control | **No** |
| Reason | Zero fills under contract thresholds on available meta (max \|rate\|=0.0005 &lt; 0.001); classic still positive OOS on narrowed window; data not full-pin |

### Freeze rules (immutable without new experiment id)

1. **Do not** rebrand this KEEP as UPGRADE without denser funding history **and** a new `run_meta` / dated artifact dir.  
2. **Do not** silent-overwrite T026 JSON under `baseline3/` — append `baseline3/YYYYMMDD_*/` if re-run.  
3. B0 remains the **only** PAPER-GO until a future contract explicitly upgrades.  
4. This record is **first-class evidence** (sparse meta + threshold non-fire), not a failed engineering ticket.  
5. GO narratives still require fee×slip **and** `funding_tca` (T014) — zero-cost-only forbidden.

---

## 7. Reproduction

```bash
python scripts/run_baseline3_challenger.py --meta-root data/s3_verify/raw
python scripts/run_baseline3_challenger.py --skip-fee-grid
python scripts/funding_tca_report.py --symbol BTC-USDT-SWAP
```

Index: [baseline-contract-index.md](./baseline-contract-index.md)  
Plan: [post-t021-implementation-roadmap.md](./post-t021-implementation-roadmap.md)

---

## 8. Non-goals

- Live 验收  
- 用 B3 结果改写 B0 PAPER-GO 历史  
- 默认打开 `portfolio_optimization`  
- 为抬升 win_rate 放宽成本门  
