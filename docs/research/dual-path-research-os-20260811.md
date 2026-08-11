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
# after Wave1+:
# python scripts/run_dual_path_report.py
# python scripts/run_dual_path_research_os.py --out data/paper_replay/dual_path/smoke.json
```

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
