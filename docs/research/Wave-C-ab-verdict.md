# Wave C — Structure / Timeframe / Execution-fidelity A/B Verdict

**Date**: 2026-08-08  
**Against**: [Candidate Baseline-0](./Candidate-Baseline-0.md) (`shared_risk_parity`, classic, 1h nested, fee/slip 0.1%)  
**Rule**: no full Optuna; fixed A/B only; upgrade to Baseline-1 only if challenger is non-worse on WFO protocol and strictly better on ≥1 primary metric.

## C1 Structure (BTC 1h + nested, fixed params)

Source: `data/paper_replay/structure_ab_1h.json` (`scripts/structure_ab_1h.py`)

| Structure | Full ret% | Full Sh | OOS meanSh | OOS sum% | pos | Verdict |
|-----------|-----------|---------|------------|----------|-----|---------|
| **classic** | 26.90 | 0.70 | **0.238** | +3.18 | 7/11 | **KEEP** |
| pullback | 15.01 | 0.56 | -0.280 | -1.12 | 3/11 | reject (hurts OOS) |
| breakout | 2.97 | 0.14 | 0.102 | +4.24 | 6/11 | reject (cum slightly higher but risk-adj worse) |

**Adjudication**: winner_by_oos_mean_sharpe = **classic**.  
Does **not** meet Baseline-1 upgrade (breakout fails Sharpe). Pullback not revisited.

Multi-symbol shared-RP structure A/B not re-run: single-symbol structure gate already eliminates challengers; multi-symbol inherits `entry_structure=classic`.

## C2 Timeframe

Sources: `data/paper_replay/mtf_matrix.json`, `mtf_matrix_4h6h_scaled.json`

| TF | OOS meanSh (nested) | OOS sum% | Notes |
|----|---------------------|----------|-------|
| 15m | 0.17 | +3.6 | weak / noisy |
| 30m | -0.45 | -2.0 | reject |
| **1h** | **0.47** | **+16.6** | **best risk-adj OOS** |
| 2h | micro+ | — | not better than 1h |
| 4h scaled | 0.15 | +6.9 | weaker than 1h |
| 6h scaled | -0.51 | -2.8 | reject |

**Adjudication**: **1h remains production research baseline**. 4h/6h scaled space does not unlock production alpha → **period line closed** for Baseline-1.

## C3 Execution fidelity (fee/slip)

Source: `data/paper_replay/reframe_sensitivity_1h.json` (BTC classic nested)

| fee / slip | return% | Sharpe | maxDD% |
|------------|---------|--------|--------|
| 0 / 0 | +40.00 | 1.03 | 6.97 |
| **0.1% / 0.1% (Baseline-0)** | **+19.12** | **0.55** | **9.43** |
| 0.2% / 0.2% | +1.41 | 0.06 | 12.91 |

- Cost drag (0 vs 0.1/0.1): **~20.9 pp**  
- Risk ablation: natural maxDD ≈ 9.4% often under 10% fuse — risk bypass is diagnostic only.

**Adjudication**: production/paper claims **must** quote 0.1%/0.1%. Zero-cost numbers are research upper bounds only.

## C4 Baseline upgrade decision

| Candidate change | Meets upgrade rule? |
|------------------|---------------------|
| breakout structure | No |
| pullback structure | No |
| 4h/6h primary TF | No |
| higher fee assumption only | N/A (sensitivity, not alpha) |
| **Keep Baseline-0** | **Yes** |

**Baseline-1**: **not created**. Baseline-0 remains the paper candidate (`PAPER-GO` from Wave B).

### Upgrade rule (codified)

Promote Baseline-N → N+1 only if, on the **same** WFO protocol as the contract:

1. All Baseline GO checks still pass for the challenger, and  
2. OOS mean Sharpe ≥ baseline, and  
3. OOS mean maxDD ≤ baseline *or* OOS cum return ≥ baseline with maxDD not worse by >20% relative, and  
4. No Optuna / synchronized search used to produce the challenger.

## C5 Regression

Focused tests after Wave A–C docs/code touchpoints:

```text
pytest tests/unit/test_paper_replay.py tests/unit/test_kill_switch*.py -q
# plus any structure/template smoke if present
```

(Executed in session; see task completion notes.)

## Explicit non-actions (Wave C)

- No new Optuna campaigns  
- No silo RP rebranded as shared alpha  
- No live trading promotion  
