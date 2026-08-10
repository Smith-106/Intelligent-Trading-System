# Baseline contract index

**Updated**: 2026-08-10 (**B4-OOS-20260810** full OOS frozen KEEP B0; B3 still frozen)  
**North star**: cost-aware paper-first research OS — not win-rate, not stars.

| ID | Doc | Signal family | Book | Status | Runner / artifacts |
|----|-----|---------------|------|--------|--------------------|
| **B0** | [Candidate-Baseline-0.md](./Candidate-Baseline-0.md) | classic `trend_following` + nested | **Multi-symbol shared RP** (BTC/ETH/SOL) | **PAPER-GO** (promoted) | `scripts/run_baseline0.py` → `data/paper_replay/baseline0/` |
| **B1** | [Candidate-Baseline-1.md](./Candidate-Baseline-1.md) | non-MA: donchian / volume_roc / rsi_thrust | BTC-only A/B | **KEEP B0** (frozen) | `scripts/run_baseline1_challenger.py` → `baseline1/` |
| **B2** | [Candidate-Baseline-2.md](./Candidate-Baseline-2.md) | mean_reversion + volatility_breakout | BTC-only A/B | **KEEP B0** (frozen) | `scripts/run_baseline2_challenger.py` → `baseline2/` |
| **B3** | [Candidate-Baseline-3.md](./Candidate-Baseline-3.md) | **`funding_rate`** thr=0.001 (+ OI) | BTC-only A/B | **KEEP B0** (T027 + **W15 confirm**) | `run_baseline3_challenger.py` → `baseline3/` + `20260810_w15/` |
| **B4** | [Candidate-Baseline-4.md](./Candidate-Baseline-4.md) · [results](./Candidate-Baseline-4-results.md) | **`funding_rate`** thr=**0.0004** (+ OI) | BTC-only A/B | **KEEP B0** (**B4-OOS-20260810**) | `run_baseline4_full_oos.py` → `baseline4/B4-OOS-20260810/` |

## Complementarity matrix

| | Trend MA (classic) | Non-MA channel/mom | Mean reversion | Vol expansion | Funding meta |
|--|--------------------|--------------------|----------------|---------------|--------------|
| B0 | **Yes** (promoted multi-symbol) | — | — | — | — |
| B1 | control only | **Yes** | — | — | — |
| B2 | control only | — | **Yes** | **Yes** | — |
| B3 | control only | — | funding mean-rev | — | **Yes** (sparse; 0 trades @ thr=0.001) |
| B4 | control only | — | funding mean-rev (lower thr) | — | **Yes** (0 trades @ thr=0.0004; KEEP B0) |

## Shared protocol pins

- Window: `2021-01-01` → `2026-08-04` (+ T011 `data_fingerprint` on runners)
- Entry TF: `1h`, gate: `nested` (signal A/B rows)
- Production cost quote: **0.1% fee + 0.1% slip**
- No Optuna for challenger promotion
- Wave-C upgrade bar: OOS meanSh > 0, ≥ classic, DD discipline, no Optuna
- GO narrative: fee×slip **and** `funding_tca` (T014)

## What “≥N contracts” means (post T027)

1. **Independent written contracts** with frozen outcomes (not N promoted GO systems).  
2. Only **B0** carries paper promotion until a later contract explicitly **UPGRADE**s.  
3. **B1 / B2 / B3** are **negative or non-upgrade results as first-class evidence**.  
4. B3 specifically freezes: **NARROWED meta window** + **zero funding_rate fills** under contract `entry_threshold=0.001` (measured max |rate|=0.0005).  
5. Funding/OI **TCA** productized in **T014**; signal-family B3 contracted T025, run T026, **frozen T027**.  
6. **B4** full OOS **B4-OOS-20260810** is **FROZEN KEEP_B0** (0 fills; max\|rate\|=0.0005; NARROWED window). Never silently edits B3 YAML or `baseline3/` artifacts; session `funding_risk_gate` remains a separate risk track (W22c). Not a W-wave — independent contract ID.

## Freeze discipline

| Rule | Applies |
|------|---------|
| No silent overwrite of sealed `adjudication*.json` / `run_meta.json` | All B* |
| Re-run → new dated dir or new contract version | B3 denser funding later |
| KEEP B0 is a valid success for challengers | B1–B3 |
| Agent must not change GitHub visibility for “open source strongest” | Ops |

## Quick re-run

```bash
python scripts/run_baseline0.py --skip-full
python scripts/run_baseline1_challenger.py
python scripts/run_baseline2_challenger.py
python scripts/run_baseline3_challenger.py --meta-root data/s3_verify/raw
```

Paper day ops: [baseline0-paper-run-checklist.md](./baseline0-paper-run-checklist.md)  
Next plan: [post-t021-implementation-roadmap.md](./post-t021-implementation-roadmap.md)
