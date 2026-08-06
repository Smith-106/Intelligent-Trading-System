# FT-001 — Strategies

| Field | Value |
|-------|-------|
| **ID** | FT-001 |
| **Status** | active |
| **Phase** | Phase 1/2 complete (7 strategies) |

## Requirements

None tracked in `.workflow/blueprint` (no SPEC/REQ files present).

## Components

| Component | Role |
|-----------|------|
| TC-003 (StrategyLayer) | L3-strategy — see tech-registry |

## Description

7 strategies via StrategyBase dual-mode API (generate_signals vectorized + on_bar incremental): trend_following, mean_reversion, elliott_wave, volatility_breakout (P1), funding_rate (P2), momentum_rotation (P3), ml_ensemble (P4). YAML-driven via strategy/catalog.py factory. ml_ensemble requires pre-trained joblib model; uses its own internal triple-barrier meta-labeling (not AIFactorEngine).

---

*Refreshed by codebase-refresh at 2026-08-05T05:39:39Z*
