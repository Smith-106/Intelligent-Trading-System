# Knowledge maintenance receipt — 2026-08-10

**Scope**: wiki + knowhow + MaestroGraph (kg) hygiene after B4/B5/T023 residual close  
**Does not**: open W28, change visibility, rewrite sealed B3/B4/B5 packages

---

## 1. Pre-maintenance snapshot

| Surface | Metric | Value |
|---------|--------|--------|
| wiki health | score | **92/100** |
| wiki | entries | 195 → later 207 |
| wiki | brokenLinks | **4** (false positives) |
| wiki | orphans | 0 → briefly 3 → **0** |
| knowledge audit | findings | **0** |
| kg | schema | v6 |
| kg | nodes (pre full sync) | ~5967 (stale mix) |

### Broken links (do not “fix” by editing sealed sessions)

All 4 from `session-20260805-maestro-knowledge-sync-20260805-052529` (+ run):

| target | nature |
|--------|--------|
| `..` | LINK_RE false positive on JSON/text |
| `"overview"` | escaped quote false positive |

**Policy**: record only; upstream maestro-flow indexer should ignore code/JSON contexts. Confirmed in sealed session notes from 2026-08-05 knowledge-sync.

---

## 2. Actions taken

### Knowhow added (searchable)

| ID | Title |
|----|--------|
| `DOC-20260810-b4-b5-funding-contracts-keep-b0` | B4/B5 funding contracts sealed KEEP_BASELINE_0 |
| `DOC-20260810-residual-ops-t023-wave-close` | Residual ops T023 + T024 + W27 close |
| `TIP-20260810-wiki-kg-false-positive-broken-links` | Wiki broken-link false positives + maint commands |

### Hub linking

- Updated `DOC-knowledge-hub.md` `related:` with the three new wiki ids  
- Orphans for new entries → **0**

### KG sync

```bash
maestro kg sync          # full
maestro kg sync --source knowhow
```

| After | Value |
|-------|--------|
| kg health | OK · staleness **0.0%** |
| knowhow_entry nodes | **44** |
| edges | ~5974 (calls/contains/constrains after full sync) |

### Search smoke

`maestro search "B4-OOS B5-ABL KEEP_BASELINE T023 residual"` hits new DOC knowhow at rank 1.

---

## 3. Post-maintenance snapshot

| Surface | Value |
|---------|--------|
| wiki health | **92/100** |
| brokenLinks | **4** (unchanged FP) |
| orphans | **0** |
| missing titles | **0** |
| knowledge audit | **0 findings** |
| kg staleness | **0.0%** |

---

## 4. Operator commands (repeatable)

```bash
maestro wiki health
maestro wiki orphans
maestro knowledge audit --json
maestro kg sync
maestro kg health
maestro kg stats
maestro search "B4-OOS KEEP_BASELINE"
maestro knowhow list
```

---

## 5. Explicit non-actions

- Did not edit sealed session JSON to chase false-positive links  
- Did not promote session knowledge candidates (pipeline 256 observed pending left for human promote)  
- Did not change GitHub visibility  
- Did not re-open B3/B4/B5 freezes  

---

---

## 6. Pass 2 — domain glossary + cross-links (same day)

### Pending pipeline (dry only)

| Item | Result |
|------|--------|
| `knowledge audit --prune` | **findings=0**, **prune_plan=[]** — no soft-prune apply |
| Sample `knowledge review` (t027 / knowledge-sync) | No mass promote; historical candidates already promoted or empty |
| Observed pending (pipeline) | **256** left for **human** promote — agent did not `--all` |

### Domain glossary (new)

Initialized `.workflow/domain/glossary.yaml` with **11** terms:

| ID | Canonical | Tier |
|----|-----------|------|
| b0 | B0 | core |
| paper-first | paper-first | core |
| b3 | B3 | core |
| b4-oos | B4-OOS | core |
| b5-abl | B5-ABL | core |
| t023 | T023 | core |
| t024 | T024 | extended |
| funding-tca | funding_tca | extended |
| paper-replay | paper_replay | core |
| keep-baseline-0 | KEEP_BASELINE_0 | core |
| cost-fidelity | cost_fidelity | extended |

`maestro domain validate` → **valid**.  
`maestro kg sync --source knowhow,domain` → **domain_term: 11**, staleness **0%**.

### Knowhow related-graph

Cross-linked:

- `DOC-research-execution-fidelity-fee-slip` ↔ B4/B5 + residual-ops DOCs  
- `DOC-research-direction-gate-wfo-overfit` → B4/B5 DOC  
- `DOC-research-multi-symbol-replay-regime-fix` → residual-ops DOC  
- New DOCs link each other + fee-slip / direction-gate classics  

### Pass-2 health

| Surface | Value |
|---------|--------|
| wiki | **92/100** · orphans **0** · broken **4** (same FP) |
| knowledge audit | **0 findings** |
| kg nodes | **~2954** (incl. 11 domain_term) |

### Commands added

```bash
maestro domain list
maestro domain search KEEP
maestro domain validate
maestro kg sync --source knowhow,domain
```

*Receipt for knowledge OS maintenance; research source of truth remains docs/research/* + sealed contracts.*
