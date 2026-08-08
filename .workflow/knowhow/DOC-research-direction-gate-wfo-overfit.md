---
title: "Direction gate + Optuna sync Sharpe 1.04 is WFO-overfit; classic 1h nested remains research baseline"
type: knowhow
category: research
tags: [wfo, overfit, direction-gate, trend-following, oos]
status: active
  - session-nonma-signal-wfo-20260808-20260808-033745
related:
  - session-mtf-expand-wfo-20260807-20260807-155411
  - DOC-research-execution-fidelity-fee-slip
  - DOC-research-multi-symbol-replay-regime-fix
  - DOC-p0-baseline-float-guard
---

# Direction-gate research conclusion (2026-08)

## Claims (OOS-first)
- Full-period Optuna on tf+nested reached Sharpe ~1.04 on the **same** sample — **not** production evidence.
- Sliding WFO (2y train / 6m fwd) collapsed OOS mean Sharpe ≈ 0; cumulative ~+1%.
- Multi-TF matrix: 1h relatively best; 12h full-window looks great but OOS fails (classic overfit demo).
- Structure A/B (classic/pullback/breakout) and non-MA families (donchian/volume_roc/rsi_thrust) did **not** beat classic on OOS mean Sharpe.
- Honest research baseline: **1h + nested + classic MA**, small positive OOS, **not** a go-live claim.

## Do not
- Promote sync-optimized params without walk-forward / holdout.
- Treat full-window Sharpe as acceptance.

## Scripts
- `scripts/wfo_tf_gate.py`, `scripts/mtf_wfo_matrix.py`, `scripts/structure_ab_1h.py`, `scripts/nonma_ab_1h.py`
