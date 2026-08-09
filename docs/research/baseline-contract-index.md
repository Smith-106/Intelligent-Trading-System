# Baseline contract index

**Updated**: 2026-08-09 (T025 — B3 contract placeholder)  
**North star**: cost-aware paper-first research OS — not win-rate, not stars.

| ID | Doc | Signal family | Book | Status | Runner / artifacts |
|----|-----|---------------|------|--------|--------------------|
| **B0** | [Candidate-Baseline-0.md](./Candidate-Baseline-0.md) | classic `trend_following` + nested | **Multi-symbol shared RP** (BTC/ETH/SOL) | **PAPER-GO** (promoted) | `scripts/run_baseline0.py` → `data/paper_replay/baseline0/` |
| **B1** | [Candidate-Baseline-1.md](./Candidate-Baseline-1.md) | non-MA: donchian / volume_roc / rsi_thrust | BTC-only A/B | **KEEP B0** (no upgrade) | `scripts/run_baseline1_challenger.py` → `baseline1/` |
| **B2** | [Candidate-Baseline-2.md](./Candidate-Baseline-2.md) | mean_reversion + volatility_breakout | BTC-only A/B | **KEEP B0** (no upgrade) | `scripts/run_baseline2_challenger.py` → `baseline2/` |
| **B3** | [Candidate-Baseline-3.md](./Candidate-Baseline-3.md) | **`funding_rate`** (+ OI) vs classic | BTC-only A/B | **CONTRACT** (T025; run=T026; verdict=T027) | `scripts/run_baseline3_challenger.py` → `baseline3/` (planned) |

## Complementarity matrix

| | Trend MA (classic) | Non-MA channel/mom | Mean reversion | Vol expansion | Funding meta |
|--|--------------------|--------------------|----------------|---------------|--------------|
| B0 | **Yes** (promoted multi-symbol) | — | — | — | — |
| B1 | control only | **Yes** | — | — | — |
| B2 | control only | — | **Yes** | **Yes** | — |
| B3 | control only | — | funding mean-rev | — | **Yes** |

## Shared protocol pins

- Window: `2021-01-01` → `2026-08-04` (+ T011 `data_fingerprint` on runners)
- Entry TF: `1h`, gate: `nested` (signal A/B rows)
- Production cost quote: **0.1% fee + 0.1% slip**
- No Optuna for challenger promotion
- Wave-C upgrade bar: OOS meanSh > 0, ≥ classic, DD discipline, no Optuna
- GO narrative: fee×slip **and** `funding_tca` (T014)

## What “≥3 contracts” means

1. **Independent written contracts** with frozen outcomes (not N promoted GO systems).
2. Only **B0** carries paper promotion until a later contract explicitly **UPGRADE**s.
3. B1/B2 are **negative results as first-class evidence**.
4. Funding/OI **TCA** productized in **T014**; **signal-family B3** contracted in **T025** (runner T026).

## Quick re-run

```bash
python scripts/run_baseline0.py --skip-full   # meta + optional subsets
python scripts/run_baseline1_challenger.py
python scripts/run_baseline2_challenger.py
# after T026:
# python scripts/run_baseline3_challenger.py
```

Paper day ops: [baseline0-paper-run-checklist.md](./baseline0-paper-run-checklist.md) (T022)  
Next plan: [post-t021-implementation-roadmap.md](./post-t021-implementation-roadmap.md)
