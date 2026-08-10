# Candidate Baseline-4 — Funding threshold sensitivity (contract only)

**Status**: **FROZEN KEEP_BASELINE_0** — full OOS run **B4-OOS-20260810**  
**Date**: 2026-08-10  
**Against**: [Baseline-0](./Candidate-Baseline-0.md)（唯一 **PAPER-GO**）  
**Results**: [Candidate-Baseline-4-results.md](./Candidate-Baseline-4-results.md)  
**Supersedes**: **nothing** — does **not** edit or re-open [B3](./Candidate-Baseline-3.md)

---

## 1. Why B4 exists (and why B3 stays frozen)

| Contract | Threshold story | Status |
|----------|-----------------|--------|
| **B3** | `entry_threshold=0.001` on `funding_rate` | **FROZEN KEEP_B0** (0 fills; max \|rate\|≈0.0005) |
| **B4（本文件）** | **Lower** entry threshold **0.0004** as a **new** signal contract | **FROZEN KEEP_B0** (0 fills @ thr; max\|rate\|=0.0005) |

B3 measured max \|funding\| under the pin window was **below** 0.001, so the
strategy never entered. That is a **valid negative result**, not a bug to
“fix” by silently editing B3 YAML.

W22c already separated **session risk gate** (`funding_risk_gate`) from B3.
B4 is the **signal-family** counterpart: if humans want a denser funding
entry rule, it must be a **new baseline version** with its own `run_meta`
directory — never overwrite `baseline3/` or `adjudication_frozen.json`.

---

## 2. Locked fields (draft)

| Field | B4 value | B3 (frozen) |
|-------|----------|-------------|
| Strategy family | `funding_rate` | same |
| `entry_threshold` | **0.0004** | 0.001 |
| `exit_threshold` | 0.00015 | 0.0003 |
| Book | BTC-only paper_replay A/B | same |
| Window pin | same as B0/B3 until re-pin | same |
| Costs | 0.1% fee + 0.1% slip + funding_tca | same |
| Optuna | **Forbidden** | same |
| Artifact dir | `data/paper_replay/baseline4/<run_id>/` | `baseline3/` |

YAML overlay (research only; does not change catalog defaults):

- `quantflow/config/strategies/funding_rate_b4_overlay.yaml`

---

## 3. Upgrade rule

Identical Wave-C bar as B1–B3: OOS meanSh > 0, ≥ classic control, DD
discipline, fee×slip + funding_tca, **no Optuna**. Default expected outcome
remains **KEEP_B0** unless evidence is overwhelming.

---

## 4. Explicit bans

- Do **not** change B3 `entry_threshold` in place  
- Do **not** treat `RiskConfig.max_funding_rate_abs` as B4 alpha  
- Do **not** claim UPGRADE without a new dated `run_meta` + adjudication  
- Do **not** auto-run B4 in CI as a promotion gate  

---

## 5. Runners

```bash
# structure smoke (W24)
python scripts/run_baseline4_challenger.py --dry-run
python scripts/run_baseline4_challenger.py --synthetic

# full OOS package (independent contract ID — not a W-wave)
python scripts/run_baseline4_full_oos.py --run-id B4-OOS-20260810
```

- Writes **only** under `baseline4/<run_id>/` (refuses `baseline3/`).  
- Full OOS attaches WFO rows, fee×slip grid, funding_tca, fingerprint, freeze.  
- Sealed verdict for B4-OOS-20260810: **KEEP_BASELINE_0** (0 challenger fills).

## 6. After freeze

1. Do **not** re-open B3 or silent-edit thr to chase fills.  
2. Optional future ablation (EMA-off / OI-off) = **new contract ID** (e.g. B5), new run dir.  
3. B0 remains sole PAPER-GO until a human UPGRADE contract.

---

*W23c draft → W24 scaffold → B4-OOS-20260810 full OOS FROZEN KEEP_B0.*
