# Candidate Baseline-4 — Funding threshold sensitivity (contract only)

**Status**: **DRAFT CONTRACT — NOT RUN** (W23c)  
**Date**: 2026-08-10  
**Against**: [Baseline-0](./Candidate-Baseline-0.md)（唯一 **PAPER-GO**）  
**Supersedes**: **nothing** — does **not** edit or re-open [B3](./Candidate-Baseline-3.md)

---

## 1. Why B4 exists (and why B3 stays frozen)

| Contract | Threshold story | Status |
|----------|-----------------|--------|
| **B3** | `entry_threshold=0.001` on `funding_rate` | **FROZEN KEEP_B0** (0 fills; max \|rate\|≈0.0005) |
| **B4（本文件）** | **Lower** entry threshold **0.0004** as a **new** signal contract | Draft only — runner optional later |

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

## 5. Runner (W24a)

```bash
python scripts/run_baseline4_challenger.py --dry-run
python scripts/run_baseline4_challenger.py --synthetic --out-dir data/paper_replay/baseline4/smoke
```

- Writes **only** under `baseline4/` (refuses paths containing `baseline3`).  
- Synthetic/dry modes are **structure smoke** — not sealed OOS UPGRADE.  
- Default promotion field remains `KEEP_BASELINE_0` / `promotion_eligible=false`.

## 6. Next steps (out of W24)

1. Optional: real meta window challenger with denser funding + T011 pin.  
2. Human adjudication only after cost-honest OOS package.  
3. Never edit B3 frozen artifacts to “make B4 pass”.

---

*W23c: contract + overlay. W24a: runner scaffold. Full OOS still deferred.*
