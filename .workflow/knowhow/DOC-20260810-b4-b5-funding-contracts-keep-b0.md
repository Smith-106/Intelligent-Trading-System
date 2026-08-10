---
title: B4/B5 funding contracts sealed KEEP_BASELINE_0
type: document
explicitId: doc-20260810-b4-b5-funding-contracts-keep-b0
created: 2026-08-10T12:42:52.570Z
related:
  - knowhow-doc-20260810-residual-ops-t023-wave-close
  - knowhow-doc-research-direction-gate-wfo-overfit
  - knowhow-doc-research-execution-fidelity-fee-slip
---

# B4/B5 funding contracts sealed KEEP_BASELINE_0

## Claims
- **B4-OOS-20260810**: funding_rate thr=0.0004 full OOS → **0 fills**, NARROWED window, **KEEP_B0**.
- **B5-ABL-20260810**: EMA×OI ablation at thr=0.0004 → OI-off unlocks ~350 fills but **≈−6%** @0.1% cost; EMA-off alone still 0 fills with OI-on → **KEEP_B0**.
- B3 thr=0.001 and B4 sealed packages must **not** be silently edited; B5 is a new contract under `baseline5/`.
- Strategy knobs `use_rate_ema` / `require_oi_confirmation` default **true** (preserve B3/B4).

## Runners
```bash
python scripts/run_baseline4_full_oos.py --run-id B4-OOS-20260810
python scripts/run_baseline5_ablation_oos.py --run-id B5-ABL-20260810
```

## Docs
- docs/research/Candidate-Baseline-4.md (+ results)
- docs/research/Candidate-Baseline-5.md (+ results)
- docs/research/baseline-contract-index.md

## Source
- commits aeda2eb (B4-OOS), d1f82a5 (B5-ABL)
