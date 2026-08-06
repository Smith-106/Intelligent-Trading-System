# FT-005 — Execution

| Field | Value |
|-------|-------|
| **ID** | FT-005 |
| **Status** | active |
| **Phase** | Phase 3 complete |

## Requirements

None tracked in `.workflow/blueprint` (no SPEC/REQ files present).

## Components

| Component | Role |
|-----------|------|
| TC-005 (ExecutionLayer) | L5-execution — see tech-registry |

## Description

Three modes: paper (PaperGateway) / sandbox (OKX testnet) / live (OKX). GatewayBase ABC, ExecutionEngine routes + emits ORDER/FILL events, OrderRouter (extracted from engine) dispatch+build_order, OrderManager timeout tracking, KillSwitch emergency flatten (fail-closed). OKX creds from env vars only.

---

*Refreshed by codebase-refresh at 2026-08-05T05:39:39Z*
