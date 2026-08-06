# FT-010 — AI Layer

| Field | Value |
|-------|-------|
| **ID** | FT-010 |
| **Status** | partial |
| **Phase** | Phase 3 partial (MIXED) |

## Requirements

None tracked in `.workflow/blueprint` (no SPEC/REQ files present).

## Components

| Component | Role |
|-----------|------|
| TC-003 (StrategyLayer) | L3-strategy — see tech-registry |

## Description

MLEnsembleStrategy ACTIVE (GradientBoosting + triple-barrier meta-labeling, expanding-window OOS, fail-closed reject-all). AIFactorEngine EXPORTED but NOT wired (no strategy/CLI calls it). FinBERT sentiment (SentimentAnalyzer/NewsCollector) IMPLEMENTED but unexported/unwired (orphaned). Qlib RD-Agent CLI skeleton (quantflow ai rdagent) with dependency guard; full LLM factor search = future (blueprint E13-S1).

---

*Refreshed by codebase-refresh at 2026-08-05T05:39:39Z*
