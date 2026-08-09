# QuantFlow product positioning (public brief)

## One-liner

**Personal / small-team Crypto mid-frequency research OS** — paper-first,
validation-gate driven (OKX). Not an institutional OEMS, not a SaaS copy-trading
bot, not a Freqtrade drop-in.

## Primary battlefield

Anti-overfit research → **GO/NO-GO gate** → paper day-session → (optional) live.

## Non-goals

- HFT / FPGA / Rust execution core rewrite
- Institutional multi-venue OEMS
- SaaS hosting, mobile, social copy-trading
- Competing on GitHub stars or exchange-connector count
- Claiming backtest byte-parity with paper/live (parity is paper↔live path only)

## Path A vs Path B (do not mix)

| Path | Command | Nested direction gate? | Use |
|------|---------|------------------------|-----|
| **A** Daily paper | `quantflow run --mode paper …` | No | Day-session ops |
| **B** Research / GO | `python scripts/run_baseline0.py` | Yes | Compare to gate.json |

## Reproduce without API keys

```bash
# 1) install
pip install -e ".[dev]"

# 2) optional: use existing local parquet under data/parquet (no OKX keys)
python scripts/preflight_baseline0_paper.py

# 3) day-session (preflight + summary only)
python scripts/paper_day_session.py

# 4) universe SLA dry-run
python scripts/universe_expand_pipeline.py --dry-run-only

# 5) inspect sample gate structure
cat docs/demo/sample_gate.json
```

Paper mode does **not** need `OKX_API_KEY`. Live is out of scope for this demo pack.

## Open-source decision (scheme B)

- **This pack** (`quantflow-docs-demo`): Apache-2.0, docs/demo only.
- **Engine repo** (`Intelligent-Trading-System`): source available; market data,
  `.env`, and paper session dumps remain local / gitignored.
- Success KPI is still **reproducible gates + cost fidelity**, not stars.
