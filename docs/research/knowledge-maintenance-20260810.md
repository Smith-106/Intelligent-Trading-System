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

*Receipt for knowledge OS maintenance; research source of truth remains docs/research/* + sealed contracts.*
