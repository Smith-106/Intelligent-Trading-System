# Candidate Baseline-2 — Complementary signal families (mean reversion / vol breakout)

**Status**: **NO UPGRADE** — keep [Baseline-0](./Candidate-Baseline-0.md) as paper candidate  
**Task**: T013  
**Date**: 2026-08-09  
**Runner**: `python scripts/run_baseline2_challenger.py`  
**Artifacts**: `data/paper_replay/baseline2/` (`complementary_wfo.json`, `fee_slip_grid.json`, `adjudication.json`, `run_meta.json`)

## Why this is “third” and complementary

| Contract | Signal logic | Role |
|----------|--------------|------|
| **Baseline-0** | classic `trend_following` + multi-symbol shared RP | **Promoted paper candidate** (PAPER-GO on multi-symbol WFO) |
| **Baseline-1** | non-MA trend-ish (`donchian` / `volume_roc` / `rsi_thrust`) | Frozen **KEEP B0** (T012) |
| **Baseline-2** | `mean_reversion` (RSI+BB) + `volatility_breakout` (ATR/KC/BB expand) | Frozen **KEEP B0** (this doc) — **anti-trend / vol-regime** complement |

**Not isomorphic**: B2 does not re-test MA crossover or Donchian channels. Mean reversion targets the opposite regime; vol breakout targets expansion after compression.

**Not in this run**: `funding_rate` (needs meta funding/OI on bar path — T014). Local `meta_funding_rate` exists but is not injected into paper_replay bars here.

## Experiment contract

| Field | Locked value |
|-------|----------------|
| Families | `mean_reversion`, `volatility_breakout` vs `classic` control |
| Direction gate | `nested` |
| Book | BTC-only paper_replay (signal A/B) |
| Timeframe | `1h` |
| Window pin | `2021-01-01` → `2026-08-04` (T011; same as B1) |
| WFO | train 24m / fwd 6m, OOS-only |
| Costs | 0.1% / 0.1% on WFO + primary full; grid 0/0, 0.1%, 0.2% |
| Optuna | **Forbidden** |

Upgrade rule: identical to [Wave C / Baseline-1](./Candidate-Baseline-1.md).

## Results (production 0.1%/0.1%)

| Label | Full ret% | Full Sh | Full maxDD% | OOS sum% | OOS meanSh | pos | Orders |
|-------|-----------|---------|-------------|----------|------------|-----|--------|
| classic | -11.81 | -0.53 | 14.12 | -2.95 | **-0.514** | 3/7 | 515 |
| mean_reversion | -14.83 | -0.67 | 19.02 | -25.20 | **-2.46** | 0/7 | 869 |
| volatility_breakout | -21.83 | -1.42 | 25.05 | -15.24 | **-2.12** | 1/7 | 1567 |

### Fee×slip (full pin)

| Label | 0/0 ret / Sh | 0.1%/0.1% | 0.2%/0.2% |
|-------|--------------|-----------|-----------|
| classic | -1.0 / -0.02 | **-11.8 / -0.53** | -21.4 / -1.03 |
| volatility_breakout | +6.7 / 0.39 | **-21.8 / -1.42** | -42.6 / -3.16 |

Vol breakout **zero-cost looks positive** then collapses under 0.1% — classic fee-drag trap (knowhow fee/slip).

## Adjudication

| Field | Value |
|-------|--------|
| **Verdict** | **KEEP_BASELINE_0** |
| upgrade | **false** |
| Best challenger (OOS meanSh) | volatility_breakout (−2.12, still ≪ classic) |
| Any challenger OOS meanSh > 0 | **No** |

**Reason**: complementary families fail OOS hard under nested+0.1% cost; no Wave-C upgrade.

## Interpretation

1. **Mean reversion** under nested gate is structurally hostile (gate prefers trend) — OOS every segment negative here.
2. **Volatility breakout** is high-turnover; fee grid shows **~28 pp** drag 0→0.1% — not a GO candidate.
3. Three frozen contracts now exist: **B0 promoted**, **B1/B2 research REJECT/KEEP records** with independent signal logic and gate paths.
4. Next alpha work should improve **B0 multi-symbol** or open a **new fixed structure** with legal protocol — not rebrand these rejects as Baseline-N promotions.

## Reproduction

```bash
python scripts/run_baseline2_challenger.py
```

Index: [baseline-contract-index.md](./baseline-contract-index.md)
