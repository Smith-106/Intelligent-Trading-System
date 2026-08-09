# Baseline contract index (≥3 contracts)

**Updated**: 2026-08-09 (T013)  
**North star**: cost-aware paper-first research OS — not win-rate, not stars.

| ID | Doc | Signal family | Book | Status | Runner / artifacts |
|----|-----|---------------|------|--------|--------------------|
| **B0** | [Candidate-Baseline-0.md](./Candidate-Baseline-0.md) | classic `trend_following` + nested | **Multi-symbol shared RP** (BTC/ETH/SOL) | **PAPER-GO** (promoted) | `scripts/run_baseline0.py` → `data/paper_replay/baseline0/` |
| **B1** | [Candidate-Baseline-1.md](./Candidate-Baseline-1.md) | non-MA: donchian / volume_roc / rsi_thrust | BTC-only A/B | **KEEP B0** (no upgrade) | `scripts/run_baseline1_challenger.py` → `baseline1/` |
| **B2** | [Candidate-Baseline-2.md](./Candidate-Baseline-2.md) | mean_reversion + volatility_breakout | BTC-only A/B | **KEEP B0** (no upgrade) | `scripts/run_baseline2_challenger.py` → `baseline2/` |

## Complementarity matrix

| | Trend MA (classic) | Non-MA channel/mom | Mean reversion | Vol expansion |
|--|--------------------|--------------------|----------------|---------------|
| B0 | **Yes** (promoted multi-symbol) | — | — | — |
| B1 | control only | **Yes** | — | — |
| B2 | control only | — | **Yes** | **Yes** |

## Shared protocol pins

- Window: `2021-01-01` → `2026-08-04` (+ T011 `data_fingerprint` on runners)
- Entry TF: `1h`, gate: `nested` (signal A/B rows)
- Production cost quote: **0.1% fee + 0.1% slip**
- No Optuna for challenger promotion
- Wave-C upgrade bar: OOS meanSh > 0, ≥ classic, DD discipline, no Optuna

## What “≥3 contracts” means after T013

1. **Three independent written contracts** with frozen outcomes (not three promoted GO systems).
2. Only **B0** carries paper promotion; B1/B2 are **negative results as first-class evidence**.
3. Funding/OI family deferred to **T014** (meta path productization).

## Quick re-run

```bash
python scripts/run_baseline0.py --skip-full   # meta + optional subsets
python scripts/run_baseline1_challenger.py
python scripts/run_baseline2_challenger.py
```
