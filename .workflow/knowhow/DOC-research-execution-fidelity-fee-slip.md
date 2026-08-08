---
title: "Research-path execution fidelity: fee/slippage dominate reported alpha"
type: knowhow
category: research
tags: [execution, fee, slippage, paper-replay, fidelity]
status: active
  - session-reframe-exec-risk-20260808-20260808-040125
related:
  - DOC-research-direction-gate-wfo-overfit
  - DOC-knowhow-live-cost-modeling-funding-fee-alerts
  - DOC-research-multi-symbol-replay-regime-fix
---

# Execution fidelity reframe (2026-08)

## Bug/gap fixed
- `build_session` previously passed only `taker_fee` into PaperGateway; now also `maker_fee` + `slippage`.
- `research_risk_bypass` (default True) keeps historical loose risk; set False for production-risk ablation.

## Sensitivity (classic 1h + nested, full window)
- Zero cost: ~+40% return / Sharpe ~1.03
- Default 0.1% fee + 0.1% slip: ~+19% / Sharpe ~0.55
- **Cost drag ≈ 21 percentage points** under default assumptions
- 0.2% fee + 0.2% slip: ~+1.4% / Sharpe ~0.06

## Priority
1. Always report fee×slip grid with strategy results
2. Dual-report research bypass vs production risk
3. Expand multi-symbol data before portfolio claims
4. Signal search is lower ROI after cost sensitivity

## Script
- `scripts/reframe_sensitivity_1h.py`
