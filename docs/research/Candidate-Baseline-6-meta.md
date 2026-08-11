# Candidate Baseline-6 — META density contract (draft)

**Contract ID**: `B6-META-20260811`  
**Status**: **DRAFT** · not GO · research-only  
**Date**: 2026-08-11  
**Wave**: improvement-plan Wave B2  

---

## 1. Intent

Open a **new** signal/data contract for denser **funding rate / open interest** history and any funding-family strategies that depend on meta density.

This contract exists because B3 suffered **0 fills** under sparse `|funding|` and short meta history relative to the OHLCV pin — a **data plane** issue, not an engine failure.

---

## 2. KEEP / frozen peers (must not edit)

| Baseline | Action |
|----------|--------|
| **B0** | KEEP · PAPER-GO portfolio contract untouched |
| **B3** | KEEP frozen (`funding_rate.yaml` entry thr=0.001) |
| **B4** | KEEP overlay under `config/research/overlays/` |
| **B5** | KEEP ablation overlay under `config/research/overlays/` |

**Forbidden**: silently lowering B3/B4/B5 thresholds to “create fills”.  
**Allowed**: new YAML under research overlays / new strategy params keyed to **B6-META**.

---

## 3. Data gates (draft)

| Gate | Draft rule |
|------|------------|
| Funding history | Prefer ≥ **90** calendar days continuous for target swap symbol before signal OOS |
| OI history | Prefer ≥ **30** days or document endpoint limits |
| Coverage report | Run `python scripts/meta_funding_oi_coverage.py` and attach JSON |
| Backfill | `python scripts/backfill_funding_oi.py --execute` only after dry-run |
| PIT | FeatureStore as-of join only (`feature_store.py` meta path) |

OKX public funding history is often **~3 months** — full multi-year parity with OHLCV is **not** a hard requirement for B6 draft acceptance; document actual coverage honestly.

---

## 4. Signal / research rules

1. Any B6 runner writes artifacts under `data/paper_replay/baseline6/` only.  
2. `promotion_eligible=false` on all research JSON.  
3. No `combined_score` with Path A overlay.  
4. IAF / RD-Agent may **suggest** features; **no** `hard_bind_entry`.  
5. Live promote: **forbidden** until T023/T024 paper sample floors + human auth.

---

## 5. Non-goals

- Engine rewrite (Nautilus/Lean/Freqtrade)  
- Multi-exchange supermarket  
- Editing sealed B0/B3–B5 params or baseline3/4/5 artifacts  
- Claiming paper↔live parity for vectorized funding backtests alone  

---

## 6. Related tooling

| Tool | Role |
|------|------|
| `scripts/meta_funding_oi_coverage.py` | Offline density probe (B1) |
| `scripts/backfill_funding_oi.py` | Optional network backfill (B1) |
| `quantflow/data/market_meta_fetcher.py` | REST funding/OI fetch |
| `quantflow/data/store.py` | `save_*` / `query_*` meta |
| `quantflow/config/research/overlays/` | Research overlays (not catalog) |

---

## 7. Exit criteria (when to promote draft → active research)

- [ ] Coverage report committed or stored under paper_replay (gitignored OK if large)  
- [ ] At least one B6 runner + independent OOS path defined  
- [ ] Explicit KEEP statement for B3–B5 in runner header  
- [ ] Unit tests: freeze thresholds for B3 still 0.001  

Until then: **DRAFT only**.
