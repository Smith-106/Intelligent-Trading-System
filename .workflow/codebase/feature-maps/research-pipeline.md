# FT-003 — Research Pipeline

| Field | Value |
|-------|-------|
| **ID** | FT-003 |
| **Status** | active |
| **Phase** | Phase 1 complete |

## Requirements

None tracked in `.workflow/blueprint` (no SPEC/REQ files present).

## Components

| Component | Role |
|-----------|------|
| TC-003 (StrategyLayer) | L3-strategy — see tech-registry |

## Description

Pure pandas/numpy backtest (BacktestEngine) + Optuna optimization (bayesian/cmaes/grid) + report generation. BacktestEngine replaced VectorBT (Py3.14+ numba incompat). Same engine used by CPCV/WFO/MC stress.

---

*Refreshed by codebase-refresh at 2026-08-05T05:39:39Z*
