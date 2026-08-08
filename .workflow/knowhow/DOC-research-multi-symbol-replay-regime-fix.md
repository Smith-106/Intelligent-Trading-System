---
title: "Multi-symbol paper replay: per-symbol regime detector + equal/shared_cap/risk_parity modes"
type: knowhow
category: research
tags: [multi-symbol, regime, paper-replay, portfolio, risk-parity]
status: active
  - knowhow-kh-multi-symbol-patterns
related:
  - session-multi-symbol-replay-20260808-20260808-045132
  - DOC-research-execution-fidelity-fee-slip
  - kh-multi-symbol-patterns
  - DOC-research-direction-gate-wfo-overfit
---

# Multi-symbol replay (2026-08)

## Critical bug
`TradingSession` used a **single** `MarketRegimeDetector` for all symbols. Interleaved multi-symbol OHLC corrupted ADX → **zero orders** on shared-book multi-symbol paper path.

### Fix
- `self._regime_detectors: dict[symbol, MarketRegimeDetector]`
- Create/update detector keyed by `bar.symbol`

## API
- `build_multi_symbol_session(...)` — per-symbol clones, shared book
- `replay_multi(...)` — timestamp-aligned multi-symbol `on_bar`
- `scripts/multi_symbol_replay.py`

## Experiment window
2021-01 → 2026-08 intersection, ~48985 1h bars, BTC+ETH+SOL, classic+nested, fee/slip 0.1%.

| mode | note |
|------|------|
| BTC-only | baseline on same window |
| equal | shared book, default caps |
| shared_cap | tighter single-name cap |
| risk_parity | **silo** inv-vol capital split — **not** comparable 1:1 to shared-book PnL |

## Data
- BTC/ETH 1h full ~2019+; SOL from ~2021 on OKX spot
- Prefer OKX over TradingView for research/live path consistency

## Caveats
- Full-window multi-symbol results are not WFO
- Silo RP high return ≠ shared-book production claim


## Shared-book symbol-level risk parity (2026-08 follow-up)

Engine opt-in: `risk.portfolio_optimization.enabled=true` + `level=symbol`.

- Tracks **close-to-close** returns per symbol (universe, not only held positions).
- Rebalances every `rebalance_every_n_bars` **unique timestamps** (not raw bar events).
- Sizing: `strategy_weight × symbol_weight` via `PortfolioManager.get_allocation_for_signal`.
- Script mode: `shared_risk_parity` in `scripts/multi_symbol_replay.py`.

### Full-window result (2021→2026-08, BTC+ETH+SOL, nested, fee/slip 0.1%)

| mode | ret% | sharpe | maxDD% | orders |
|------|------|--------|--------|--------|
| equal | +22.63 | 0.34 | 24.7 | 1539 |
| shared_cap | +21.00 | 0.35 | 22.2 | 1541 |
| **shared_risk_parity** | **+5.14** | **0.24** | **8.5** | 1547 |
| silo risk_parity | +226.87 | 0.35 | 9.0 | 1547 |
| btc_only | -11.81 | -0.53 | 14.1 | 515 |

Shared RP trades off return for lower drawdown vs equal; silo RP is a different capital method and must not be compared 1:1.


## WFO OOS (2026-08 follow-up) — equal vs shared_risk_parity

Script: `scripts/wfo_shared_rp.py` (2y implied cadence via 6m steps on OOS-only windows; fixed classic+nested params).

7 OOS segments 2023-01 → 2026-07, fee/slip 0.1%, BTC+ETH+SOL:

| mode | meanRet% | meanSh | meanDD% | cumRet% | pos |
|------|----------|--------|---------|---------|-----|
| equal | +5.76 | 0.623 | 8.25 | +41.32 | 5/7 |
| **shared_risk_parity** | **+1.82** | **0.727** | **2.55** | +12.93 | 5/7 |

**Winner by mean OOS Sharpe: shared_risk_parity** — lower return, higher risk-adjusted + much lower drawdown. Full-window equal still higher cumulative; WFO confirms RP is the more stable shared-book allocator.

