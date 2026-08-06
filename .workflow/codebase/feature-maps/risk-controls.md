# FT-006 — Risk Controls

| Field | Value |
|-------|-------|
| **ID** | FT-006 |
| **Status** | active |
| **Phase** | Phase 2 complete |

## Requirements

None tracked in `.workflow/blueprint` (no SPEC/REQ files present).

## Components

| Component | Role |
|-----------|------|
| TC-004 (SignalRiskLayer) | L4-signal-risk — see tech-registry |

## Description

RiskEngine 7-check short-circuit pipeline: position_limit -> portfolio_limit -> strategy_budget -> daily_loss -> weekly_loss -> drawdown -> VaR. Half-Kelly position sizing (PositionSizer, not ScalingPositionSizer), VaR/CVaR (historical + bootstrap_cvar diagnostic CI), drawdown circuit breaker, KillSwitch shared instance. Note: no ScalingPositionSizer class exists; PositionSizer.size emits notional wrapped in PositionRequest by session.

---

*Refreshed by codebase-refresh at 2026-08-05T05:39:39Z*
