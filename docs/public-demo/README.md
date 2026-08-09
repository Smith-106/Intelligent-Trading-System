# QuantFlow — public docs & demo pack

**License:** Apache-2.0（见 `LICENSE`）  
**Scope:** documentation + synthetic gate examples only.  
**Not included:** trading engine source, market data, live credentials, private research PnL.

## What is QuantFlow?

A **personal / small-team Crypto mid-frequency research OS** (OKX-oriented):

- paper-first  
- validation-gate driven (CPCV / DSR / PBO / WFO → GO/NO-GO)  
- cost fidelity: fee×slip grids required for promotion narratives  

It is **not** an institutional OEMS, not a SaaS copy-trading bot, and not a Freqtrade clone.

See [POSITIONING.md](./POSITIONING.md).

## Path A vs Path B

| Path | Meaning | Nested direction gate? |
|------|---------|------------------------|
| **A** | Daily paper session | No |
| **B** | Research / GO parity scripts | Yes |

Never compare Path A PnL to Path B `gate.json` numbers.

## Files

| File | Purpose |
|------|---------|
| `POSITIONING.md` | Product positioning & non-goals |
| `sample_gate.json` | **Synthetic** GO/NO-GO shape (+ cost fields) |
| `sample_fee_slip_grid.json` | Why zero-cost Sharpe is not enough |
| `LICENSE` / `NOTICE` | Apache-2.0 |
| `PUBLISH.md` | How to publish this folder as a public repo |

## Hard rules (also enforced in private core)

1. No paper promotion without fee×slip grid (zero-cost + production cells).  
2. Zero-cost-only GO is rejected.  
3. Default portfolio optimization stays **off** unless an overlay enables it.  
4. Success ≠ GitHub stars.

## Full engine

Implementation: [Smith-106/Intelligent-Trading-System](https://github.com/Smith-106/Intelligent-Trading-System)  
This pack is intentionally **thin** (docs + synthetic samples only) so readers can evaluate the research-OS philosophy without market data dumps or credentials.

Research artifacts (`data/`, live keys, session logs) stay out of both this pack and default gitignore of the engine repo.
