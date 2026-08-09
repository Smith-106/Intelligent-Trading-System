# Candidate Baseline-1 — Second signal family (non-MA) adjudication

**Status**: **NO UPGRADE** — keep [Baseline-0](./Candidate-Baseline-0.md) as paper candidate  
**Task**: T012  
**Date**: 2026-08-09  
**Runner**: `python scripts/run_baseline1_challenger.py`  
**Artifacts**: `data/paper_replay/baseline1/` (`nonma_wfo.json`, `fee_slip_grid.json`, `adjudication.json`, `run_meta.json`)

## Experiment contract (challenger protocol)

| Field | Locked value |
|-------|----------------|
| Challenger families | `non_ma_signal` · `donchian` / `volume_roc` / `rsi_thrust` |
| Control | `trend_following` classic (same as B0 signal side) |
| Direction gate | `nested` |
| Book | **BTC-only** paper_replay (signal A/B; not multi-symbol RP) |
| Timeframe | `1h` |
| Window pin | `2021-01-01` → `2026-08-04` (T011) |
| WFO | train **24m** / fwd **6m**, OOS-only |
| Costs (WFO + primary full) | `taker_fee=0.001`, `slippage=0.001` |
| Fee×slip grid | 0/0, 0.1%/0.1%, 0.2%/0.2% on full pin |
| Optuna | **Forbidden** |

> Multi-symbol shared-RP remains defined only on Baseline-0. Baseline-1 here answers:  
> *Does a non-MA signal family beat classic on the same WFO+cost protocol enough to replace classic as the research signal core?*

## Upgrade rule (Wave C, codified)

Promote only if **all** hold on OOS (production fee):

1. Challenger OOS mean Sharpe **> 0**
2. Challenger OOS sum return **≥ 0**
3. OOS mean Sharpe **≥** classic
4. Full-window maxDD not worse than classic by **>20%** relative (or return compensates under the automated checks)
5. No Optuna / synchronized search

Else: **KEEP Baseline-0** (challengers may remain research references).

## Results (pinned window, production 0.1%/0.1%)

| Label | Full ret% | Full Sh | Full maxDD% | OOS sum% | OOS meanSh | pos | Orders (full) |
|-------|-----------|---------|-------------|----------|------------|-----|---------------|
| classic | -11.81 | -0.53 | 14.12 | -2.95 | **-0.514** | 3/7 | 515 |
| **donchian** | **+3.43** | **0.20** | **5.60** | -5.06 | **-0.704** | 2/7 | 597 |
| volume_roc | -11.96 | -0.80 | 14.80 | -11.81 | -1.82 | 1/7 | 1139 |
| rsi_thrust | -14.70 | -1.52 | 15.33 | -6.92 | -1.59 | 2/7 | 663 |

WFO segments on this pin: **7** (not the longer 11-seg historical nonma_ab span — that used a different history length to `--end`).

### Fee×slip grid (full pin)

| Label | fee/slip | ret% | Sharpe |
|-------|----------|------|--------|
| classic | 0/0 | -1.01 | -0.02 |
| classic | **0.1%/0.1%** | **-11.81** | **-0.53** |
| classic | 0.2%/0.2% | -21.41 | -1.03 |
| donchian | 0/0 | +14.85 | 0.78 |
| donchian | **0.1%/0.1%** | **+3.43** | **0.20** |
| donchian | 0.2%/0.2% | -6.83 | -0.37 |

**Cost drag (donchian 0 → 0.1%) ≈ 11.4 pp** — zero-cost still overstates; 0.2% turns donchian negative.

## Adjudication

| Decision | Value |
|----------|--------|
| **Verdict** | **KEEP_BASELINE_0** |
| **upgrade_to_baseline1** | **false** |
| Best challenger by OOS meanSh | donchian (still **negative** OOS meanSh) |
| Any challenger OOS meanSh > 0 | **No** |

**Reason (machine)**: best challenger=donchian OOS meanSh=-0.704 vs classic=-0.514; fails OOS Sharpe > 0 and fails ≥ classic.

### Interpretation (human)

1. **Donchian** has the only **positive full-window** return at 0.1%/0.1% and lower DD, but **WFO OOS mean Sharpe is worse than classic and negative** → not a production signal upgrade.
2. **volume_roc / rsi_thrust** fail full and OOS hard — research dead-ends under this protocol.
3. Classic BTC-only nested on this pin is itself weak on OOS (meanSh < 0) — **Baseline-0 paper claim remains multi-symbol shared-RP**, not this BTC-only control table. This table is only for **signal-family** ranking.
4. **Baseline-1 is not created** as a promoted contract. This document is the **frozen REJECT/KEEP record** required by T012.

## Non-goals for this run

- Did not re-tune parameters (would violate no-Optuna)
- Did not multi-symbol RP the non-MA families (optional follow-up if a family clears single-name OOS first)
- Did not claim win-rate improvements

## Reproduction

```bash
python scripts/run_baseline1_challenger.py
# pin override:
python scripts/run_baseline1_challenger.py --start 2021-01-01 --end 2026-08-04
```

Compare fingerprint: `run_meta.json` → `data_fingerprint.aggregate`.

## Next research options (not auto tasks)

- Only revisit a family after a **protocol-legal** structural change (new fixed structure, not Optuna)
- T013 third baseline should pick a **complementary** line (e.g. funding/OI) only if data path is complete — same upgrade bar
- Improve **Baseline-0 multi-symbol** evidence rather than forcing a weak single-name challenger
