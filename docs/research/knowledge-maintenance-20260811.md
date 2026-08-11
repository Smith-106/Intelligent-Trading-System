# Knowledge maintenance receipt — 2026-08-11

**Scope**: wiki + knowhow + MaestroGraph (kg) hygiene after IMP-01…05 + v0.7.0 release  
**Does not**: mass-promote historical `pending_observed`; rewrite sealed session JSON; open new feature waves

---

## 1. Pre-maintenance snapshot

| Surface | Metric | Value |
|---------|--------|--------|
| wiki health | score | **92/100** |
| wiki | entries | 232 → **242** |
| wiki | brokenLinks | **4** (false positives, unchanged) |
| wiki | orphans | **0** |
| knowledge audit | findings | **0** |
| knowledge audit | pipeline.pending_observed | **265** (historical ledgers) |
| knowledge audit | pipeline.pending_corroborated | **0** |
| knowledge audit | pipeline.promoted | **100** |
| kg | status | was **stale/warn** → after sync **pass** |
| kg | nodes / edges (pre) | ~2954 / ~5974 |

### Broken links (do not “fix”)

Same 4 FP as 2026-08-10:

| source | target |
|--------|--------|
| `session-20260805-maestro-knowledge-sync-…` | `..` |
| same + run wiki-manage | `\"overview\"` |

Policy: record only — see `TIP-20260810-wiki-kg-false-positive-broken-links`.

### Recent sealed sessions (promote status)

| Session | Candidates |
|---------|------------|
| cleanup-release-070 | 3/3 promoted |
| imp03-05-exec | 3/3 promoted |
| imp01-02-exec | 4/4 promoted |
| oss-improve-plan | 8/8 promoted |
| pathb-iaf-followup | 4/4 promoted |
| iaf-adversarial-closeout | 10/10 promoted |

Historical sessions still carry large **uncorroborated** pending blobs (e.g. 20260802 UI/WCAG). **Not** mass-promoted.

---

## 2. Actions taken

### KG sync

```bash
maestro kg sync --json
```

| After | Value |
|-------|--------|
| kg health | **pass** · stale **false** · schema **v8** |
| integrity / FK | ok |
| nodes / edges | **3238** / **6817** |
| stalenessRatio | **0** |
| knowhow_entry | 45 → **47** after new docs + re-sync |
| spec_entry | **197** |

### Knowhow added

| File | Title |
|------|--------|
| `DOC-20260811-imp-residual-research-os-v070.md` | IMP residual research OS (v0.7.0) |
| `TIP-20260811-knowledge-pending-observed-not-auto-promote.md` | pending_observed ≠ auto-promote queue |

### Hub linking

- Updated `DOC-knowledge-hub.md` `related:` with both new wiki ids  
- Orphans remain **0**

### Soft-prune

```bash
maestro knowledge audit --scope all --prune --json
```

→ **no prune plan** (nothing safe to soft-prune).

---

## 3. Post-maintenance snapshot

| Surface | Value |
|---------|--------|
| wiki health | **92/100** |
| brokenLinks | **4** (FP) |
| orphans | **0** |
| missing titles | **0** |
| knowledge audit findings | **0** |
| kg | pass · not stale · staleness 0 |

### Search smoke

```bash
maestro search "IMP residual dual-path promotion PIT"
maestro search "pending_observed not auto-promote"
```

---

## 4. Operator commands (repeatable)

```bash
set PYTHONUTF8=1
maestro knowledge audit --scope all --json
maestro knowledge audit --scope all --prune --json   # plan only; add --apply only when plan non-empty
maestro wiki health
maestro wiki orphans
maestro kg sync --json
maestro kg health --json
maestro kg stats --json
# per sealed session:
maestro knowledge review <session-id> --json
# promote only adjudicated uniques:
maestro knowledge promote <session-id> --resolve <KDC-id> --as unique --reason "..."
```

---

## 5. Explicit non-actions

- Did **not** bulk-promote 783 historical ledger `pending` rows  
- Did **not** edit sealed session JSON to “fix” broken links  
- Did **not** `kg rebuild` (hash-aware sync sufficient)
