# Candidate Baseline-0 — Run Results

**Ran**: 2026-08-08 via `python scripts/run_baseline0.py`  
**Contract**: [Candidate-Baseline-0.md](./Candidate-Baseline-0.md)  
**Artifacts**: `data/paper_replay/baseline0/`

## Full-window (2021-01-01 → 2026-08-04, 48985 bars, fee/slip 0.1%)

| Mode | return% | Sharpe | maxDD% | orders | Notes |
|------|---------|--------|--------|--------|-------|
| btc_only | -11.81 | -0.53 | 14.12 | 515 | same window baseline |
| equal (shared) | **+22.63** | 0.34 | 24.71 | 1539 | shared book |
| shared_cap | +21.00 | 0.35 | 22.22 | 1541 | shared book |
| **shared_risk_parity** | **+5.14** | **0.24** | **8.50** | **1547** | **Baseline-0 primary** |
| risk_parity (silo) | +226.87 | 0.35 | 9.03 | 1547 | **not comparable** 1:1 to shared |

Shared RP last weights (engine): BTC≈0.50 / ETH≈0.25 / SOL≈0.25.

## WFO OOS (train 24m / fwd 6m, 7 segments)

| Mode | meanRet% | meanSh | meanDD% | cumRet% | pos |
|------|----------|--------|---------|---------|-----|
| equal | +5.76 | 0.623 | 8.25 | +41.32 | 5/7 |
| **shared_risk_parity** | **+1.82** | **0.727** | **2.55** | **+12.93** | **5/7** |

Winner by mean OOS Sharpe: **shared_risk_parity**.

### Segment detail (shared_risk_parity)

| OOS window | ret% | Sharpe | maxDD% |
|------------|------|--------|--------|
| 2023-01→07 | +5.50 | 2.45 | 1.97 |
| 2023-07→2024-01 | +6.07 | 3.44 | 1.22 |
| 2024-01→07 | +2.08 | 0.98 | 2.27 |
| 2024-07→2025-01 | +4.28 | 2.34 | 1.51 |
| 2025-01→07 | -1.93 | -1.42 | 3.13 |
| 2025-07→2026-01 | +0.95 | 0.65 | 2.65 |
| 2026-01→07 | -4.23 | -3.35 | 5.10 |

## GO gate evaluation (paper candidate)

| # | Rule | Result | Pass? |
|---|------|--------|-------|
| 1 | OOS mean_sharpe > 0 | 0.727 | **PASS** |
| 2 | OOS cum_return_pct ≥ 0 | +12.93 | **PASS** |
| 3 | OOS mean_max_dd ≤ equal | 2.55 ≤ 8.25 | **PASS** |
| 4 | pos_segments ≥ 50% | 5/7 ≈ 71% | **PASS** |
| 5 | Full-window orders > 0 | 1547 | **PASS** |

### Verdict

**PAPER-GO (research candidate)** — shared symbol RP clears the contractual WFO gates vs equal on risk-adjusted OOS and drawdown.

**Not a live production claim**: absolute OOS mean return is modest; two recent windows negative; no trading-live evidence required this round. Wave C may only challenge via fixed structure/TF/cost A/B under the same protocol.

## Machine-readable gate

```json
{
  "baseline_id": "Baseline-0",
  "primary_mode": "shared_risk_parity",
  "decision": "PAPER-GO",
  "checks": {
    "oos_mean_sharpe_gt_0": true,
    "oos_cum_return_ge_0": true,
    "oos_mean_dd_le_equal": true,
    "pos_segments_ge_half": true,
    "full_orders_gt_0": true
  },
  "metrics": {
    "oos_mean_sharpe": 0.7268,
    "oos_cum_return_pct": 12.9347,
    "oos_mean_max_dd_pct": 2.5517,
    "oos_pos_segments": 5,
    "oos_n_segments": 7,
    "full_return_pct": 5.143,
    "full_sharpe": 0.2437,
    "full_max_dd_pct": 8.504,
    "full_orders": 1547
  },
  "artifacts": {
    "full": "data/paper_replay/baseline0/multi_symbol_replay.json",
    "wfo": "data/paper_replay/baseline0/wfo_shared_rp.json",
    "meta": "data/paper_replay/baseline0/run_meta.json"
  }
}
```

## Paper operator overlay

See `quantflow/config/paper_baseline0_overlay.yaml` + contract handbook section in `Candidate-Baseline-0.md`.
