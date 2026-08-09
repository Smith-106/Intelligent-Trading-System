# Contributing to QuantFlow

Thanks for your interest. QuantFlow is a **paper-first research OS** for personal / small-team crypto (OKX). Please read this before opening issues or PRs.

## Product boundaries (non-negotiable)

| Do | Don't |
|----|--------|
| Cost-aware validation (fee×slip + funding_tca) | Promote on zero-cost Sharpe alone |
| Path A (daily paper) vs Path B (nested gate) kept separate | Compare Path A PnL to `gate.json` |
| Paper readiness floors before live promote | Skip `paper_evidence` on promote |
| Fail-closed gates | Hide failures with broad skips |

**Non-goals**: Rust HFT rewrite, market making, multi-exchange supermarket, SaaS copy-trading, stars-as-KPI.

## Current open-source posture

- **Scheme B (active)**: public docs/demo — [quantflow-docs-demo](https://github.com/Smith-106/quantflow-docs-demo) (Apache-2.0).
- **Scheme C (optional, not automatic)**: core public only after human review of `docs/research/open-source-c-gate-checklist.md` and a green `python scripts/oss_c_gate.py`.
- Agents / automation **must not** change GitHub repository visibility.

## Development setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -e ".[dev]"
ruff check --fix . && ruff format .
mypy quantflow/
pytest tests/ -m "not live" -q
```

API keys: **only** via environment / `.env` (never commit). See `.gitignore`.

## PR checklist

1. `ruff check` + `ruff format --check` clean on touched paths.
2. Focused tests for the change; no secret material in diffs.
3. If touching validation/register/promote: keep **fail-closed** cost + funding + paper readiness behavior.
4. If touching research runners: preserve T011 pin fields / fingerprints where applicable.
5. Docs: update roadmap or research notes only when behavior/contracts change.
6. Run when relevant:
   - `python scripts/demo_public_pack.py --check`
   - `python scripts/oss_c_gate.py --quick`
   - `python scripts/preflight_baseline0_paper.py` (needs local parquet)

## What we merge

- Bug fixes, gate hygiene, docs clarity, tests, paper-path safety.
- New strategies via catalog + YAML + tests (see `quantflow/strategy/catalog.py`).

## What we usually reject

- “Make win rate higher” without cost/WFO evidence.
- Live trading shortcuts that bypass Kill Switch / readiness.
- Broad dependency or engine rewrites without an approved plan.
- Committing `data/`, real `gate.json` alpha dumps, or credentials.

## Security / secrets

- Report suspected credential leaks privately when possible.
- Before any path-C discussion: full-history secret scan (e.g. gitleaks) + key rotation if needed.
- Local heuristic: `python scripts/oss_c_gate.py` (not a history scanner).

## License

See root `LICENSE`. Public docs-demo subset uses Apache-2.0 (`docs/public-demo/LICENSE`). Path C license choice for core is a **human** decision recorded in the open-source brief.
