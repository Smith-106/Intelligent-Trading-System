---
title: "IMP residual research OS (v0.7.0)"
type: knowhow
tags: [research-os, dual-path, promotion, pit, multi-symbol, monitoring, v0.7]
status: active
related:
  - knowhow-doc-knowledge-hub
  - knowhow-doc-research-execution-fidelity-fee-slip
  - knowhow-doc-research-direction-gate-wfo-overfit
  - knowhow-doc-research-multi-symbol-replay-regime-fix
  - knowhow-tip-20260810-wiki-kg-false-positive-broken-links
  - "spec:project:architecture-constraints"
---

# IMP residual research OS (v0.7.0)

**Date**: 2026-08-11  
**Release**: QuantFlow v0.7.0  
**Scope**: residual-first wiring after OSS adversarial analysis — **not** engine rewrite.

## Locked constraints

- `promotion_eligible=false` for research dual-path / Path B OOS
- Research claims **honest** `execution_path=vectorized` (do not fake `paper_replay` GO)
- No `combined_score` merging Path A and Path B
- No multi-exchange / live promote in this pack
- Feature Store PIT fail-closed on lookahead

## Landed modules (IMP-01…05)

| ID | Surface | Key paths |
|----|---------|-----------|
| IMP-01 | promotion attach + fingerprint | `dual_path_report.py`, `path_b_oos.py`, `promotion_path.py` |
| IMP-02 | Path B OOS thickness + cost | `path_b_oos.py`, `scripts/run_path_b_oos.py` |
| IMP-03 | PIT audit | `quantflow/data/pit_audit.py` |
| IMP-04 | multi-symbol dual-path | `multi_symbol_dual_path.py`, `scripts/run_multi_symbol_dual_path.py` |
| IMP-05 | session health + alert taxonomy | `session_health.py`, `docs/ops/alert-taxonomy-session-health.md` |

## Verify

```bash
set PYTHONUTF8=1
python -m pytest tests/unit/test_dual_path_report.py tests/unit/test_path_b_oos.py tests/unit/test_pit_audit.py tests/unit/test_multi_symbol_dual_path.py tests/unit/test_session_health.py -q
```

## Docs

- `docs/research/oss-adversarial-improvement-plan-20260811.md`
- `docs/research/team-swarm-oss-improve-20260811.md`
- `docs/release/v0.7.0.md`
