# Dual-Path Research OS — 2026-08-11

**Contract**: `DUAL-PATH-RESEARCH-OS-20260811`  
**Source**: [team-swarm-iaf-tpsl-adversarial-20260811.md](./team-swarm-iaf-tpsl-adversarial-20260811.md)  
**Profiles**: `quantflow/config/research/dual_path_profiles.yaml`

---

## 1. Purpose

把 Team Swarm 双产品共识工程化为可重复研究操作系统：

| Path | 产品叙事 | 默认 profile |
|------|----------|--------------|
| **A** continuous overlay | 冲 excess vs BTC HODL | `primary_w30` reduce_off MA96/400 w=0.30 |
| **B** discrete TPSL | 控 maxDD / R:R / 胜率 | dual-MA lag-1 **SL4% / TP10% / min_rr 2.5** |

**禁止** `combined_score` / 加权总分进入 decision 或晋级。  
**禁止** 静默改 B0/B3–B5 冻结合同。  
**禁止** 默认把 IAF 因子 hard-bind 进 live entry。

---

## 2. Pin-window anchors (taker 10bp+10bp, BTC 1h)

| Path | Excess vs HODL | maxDD | notes |
|------|---------------:|------:|-------|
| A `primary_w30` | **+47.09 pp** | ~69.5% | no pen-trade winrate |
| B TPSL 4/10 RR2.5 | **+3.98 pp** | **~21.1%** | wr~39% payoff~2.5 PASS |

---

## 3. Pipeline order

```text
causal_preflight → CPCV/DSR/WFO (honest n_trials) → cost → vs-BTC → paper_replay
```

IAF = **pruneable research library** only (correlation prune + CPCV before any candidate entry filter).

---

## 4. Reproduce

```bash
set PYTHONUTF8=1
python -m pytest tests/unit/test_dual_path_profiles.py -q
python scripts/run_btc_beta_overlay_eval.py --fee 0.001 --slip 0.001
python scripts/run_btc_tpsl_eval.py --sl 0.04 --tp 0.10 --min-rr 2.5
python scripts/run_dual_path_report.py
python scripts/run_dual_path_research_os.py --out data/paper_replay/dual_path/research_os_full.json
quantflow validate --method causal_preflight --strategy trend_following
```

### Full OS pin result (2026-08-11 closeout)

| Path | excess | maxDD | gate vs HODL | validation |
|------|-------:|------:|--------------|------------|
| A primary_w30 | +47.09pp | 69.47% | PASS | n/a (continuous) |
| B TPSL 4/10 | +3.98pp | 21.13% | PASS product | CPCV **NO-GO** PBO=0.75 (honest; promotion_eligible=false) |

Notes:
- Path B product gate (beat HODL under taker costs) can PASS while anti-overfit CPCV fails — dual reporting is intentional.
- Default fixed barrier uses no in-gate Optuna; multi-point grids force `optimize_method=grid` (discrete axes break bayesian `(low,high)`).
- IAF prune example kept: cci_20, aroon_up/down, cmf_20, realized_vol_20, trix_15 (research-only).

---

## 5. Implementation map

| Piece | Status |
|-------|--------|
| IAF + causal | done `b19e34f` |
| TPSL sim | done `3d4f6e7` |
| Overlay primary | done `b167eb7` |
| dual_path profiles YAML | **done** Wave0 |
| dual_path_report | **done** Wave1 |
| iaf_prune | **done** Wave2 |
| n_trials + TPSL gate adapter | **done** Wave3 |
| causal_preflight CLI | **done** Wave4 |
| run_dual_path_research_os | **done** Wave5 |

---

## 6. One-liner

> Maximize excess with continuous overlay w=0.30; control DD/R:R with discrete TPSL 4/10; never merge scores; gate with causal + CPCV/DSR/WFO/cost/vs-BTC; IAF is a pruneable library.

## 5. Post-closeout extensions (2026-08-11)

### Path B multi-window OOS + honest n_trials

```bash
set PYTHONUTF8=1
python scripts/run_path_b_oos.py --n-windows 4 --mode rolling --out data/paper_replay/dual_path/path_b_oos.json
```

- `research_go=GO_DISCUSS` only when honest n_trials AND ≥50% OOS windows beat BTC AND median OOS excess>0.
- **Never** `promotion_eligible=true`; GO_DISCUSS is research discussion only.
- Pin run (rolling 4-window): see `data/paper_replay/dual_path/path_b_oos.json`.

### IAF prune → CPCV (no hard-bind)

```bash
python scripts/run_iaf_prune_cpcv.py --out data/paper_replay/dual_path/iaf_prune_cpcv.json
```

- Kept factors after Spearman prune are **research-only**; `hard_bind_entry=false` always.
- Pin run: CPCV NO-GO (PBO≈0.73) → do not bind IAF to entry/freeze.

### Knowledge promote (closeout session)

Session `20260811-iaf-adversarial-closeout-20260811-080734`: 10/10 candidates promoted (pending=0).

