# QuantFlow demo pack (no secrets)

Synthetic + scripted artifacts so a third party can understand **how** QuantFlow
gates research without any exchange credentials.

| File | Purpose |
|------|---------|
| `POSITIONING.md` | Product positioning and non-goals |
| `sample_gate.json` | Shape of a GO/NO-GO report (+ cost fidelity fields) |
| `sample_fee_slip_grid.json` | Cost-grid narrative requirements |
| `../research/baseline0-paper-run-checklist.md` | Full paper day checklist |

## Quick commands

```bash
python scripts/demo_public_pack.py --check
python scripts/preflight_baseline0_paper.py
python scripts/paper_day_session.py
python scripts/universe_expand_pipeline.py --symbols BTC/USDT,ETH/USDT,SOL/USDT --dry-run-only
```

## Hard rules reflected here

1. No GO without fee×slip grid (zero + production cells).
2. Zero-cost-only alpha is rejected at register.
3. Path A paper PnL ≠ Path B nested `gate.json`.
4. Default `portfolio_optimization.enabled=false` in `default.yaml`.
