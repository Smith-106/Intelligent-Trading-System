---
title: "Learnings 2026-08-11: params, performance paths, structure"
type: knowhow
tags: [learning, dual-path, overlay, structure, paper-first]
status: active
related:
  - knowhow-doc-knowledge-hub
  - knowhow-doc-20260811-imp-residual-research-os-v070
  - knowhow-doc-research-execution-fidelity-fee-slip
  - "spec:project:architecture-constraints"
  - "spec:project:learnings"
---

# Learnings 2026-08-11: params, performance paths, structure

## What the evidence taught us

### Parameters (do **not** re-sweep blindly)

| Lever | Locked learning | Why |
|-------|-----------------|-----|
| Path A `overlay_weight` | **0.30** primary (not 0.25) | Taker pin: excess **+47.1pp** vs prior **~+40pp**; maxDD slightly better |
| Path A mode | **reduce_off** | Beats add_on under taker costs on pin window |
| MA | **96 / 400** | Lower turnover dominates denser grids |
| DD throttle | **default off** | Cuts DD but can lose vs HODL in bulls |
| Path B barriers | SL4% / TP10% / min_rr 2.5 | Control sleeve: maxDD~21%, wr~39%, payoff~2.5 |
| Path B OOS | default **6** windows | IMP-02 thickness; still **GO_DISCUSS** not GO |
| B0 book | **shared_risk_parity** | PAPER-GO; full ret modest (+5.14%) but OOS Sharpe strong |
| Silo `risk_parity` | **never** market as shared | +226% not 1:1 comparable |

### Path semantics (structure of truth)

1. **paper_replay** (`multi_symbol_replay`, B0) = virtual event book — ops/T023 path.
2. **vectorized research** (dual-path, overlay eval, path_b_oos) = research-only; `execution_path=vectorized`, `promotion_eligible=false`.
3. **parity** = paper↔live only; **backtest ≠ paper**.
4. **No `combined_score`** merging Path A and Path B.
5. **IAF never `hard_bind_entry=true`** — prune is research attach only.

### Ops residual (not optimizable away)

- T023 streak is **calendar** (was 4/7 on 2026-08-11); no backfill.
- T024 promote needs real fills + ≥7 days; dry-run fail-closed is success.

### Structure hygiene that paid off

- Config profiles live in YAML (`dual_path_profiles.yaml`) + named Python profiles (`btc_overlay_profiles.py`).
- Research modules grew faster than `research/__init__.py` exports — **export the dual-path/PIT surface** so DX matches reality.
- IMP residual waves (01–05) land as **wiring + audit + report**, not engine rewrites.
- Soft knowledge: `pending_observed` ≠ auto-promote queue.

## Anti-patterns (reject)

- Raising overlay weight past ~0.30 without cost matrix re-proof.
- Treating Path B validation **NO-GO** or OOS **GO_DISCUSS** as silent GO.
- Using silo RP return as Baseline-0 primary narrative.
- Opening W28+ engineering waves for residual polish.
- Mass-promoting historical knowledge pending blobs.

## Next safe polish (not alpha chase)

1. IMP-06: regression-lock `hard_bind_entry is False` across dual-path suite.
2. Catalog DX: SimpleStrategy discoverability.
3. `docs/research/README.md` index of north-star docs.
4. Keep primary params; optimize **process** (T023 days, evidence), not frozen B0.
