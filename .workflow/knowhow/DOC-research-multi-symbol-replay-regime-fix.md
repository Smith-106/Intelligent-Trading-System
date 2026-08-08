---
title: "Multi-symbol paper replay: per-symbol regime detector + equal/shared_cap/risk_parity modes"
type: knowhow
category: research
tags: [multi-symbol, regime, paper-replay, portfolio, risk-parity]
status: active
related:
  - session-multi-symbol-replay-20260808-20260808-045132
  - knowhow-kh-multi-symbol-patterns
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
