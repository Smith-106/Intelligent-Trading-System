# FT-004 — Anti-Overfitting Validation

| Field | Value |
|-------|-------|
| **ID** | FT-004 |
| **Status** | active |
| **Phase** | Phase 2 complete |

## Requirements

None tracked in `.workflow/blueprint` (no SPEC/REQ files present).

## Components

| Component | Role |
|-----------|------|
| TC-003 (StrategyLayer) | L3-strategy — see tech-registry |

## Description

CPCV (PBO<0.5) + DSR (>0.95) + PBO + WFO (OOS eff>50%, rolling+anchored) + GO/NO-GO gate. Triple-barrier labeling, min TRL, signal quality metrics, lookahead AST scan, Monte Carlo stress (trade-shuffle + returns-bootstrap, diagnostic non-gating).

---

*Refreshed by codebase-refresh at 2026-08-05T05:39:39Z*
