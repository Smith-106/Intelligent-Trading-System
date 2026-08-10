---
title: Wiki broken links often false positives in sealed JSON
type: tip
explicitId: tip-20260810-wiki-kg-false-positive-broken-links
created: 2026-08-10T12:42:53.789Z
---

# Wiki/KG maintenance notes (false-positive broken links)

## Claims
- Wiki health ~92/100 with **4 brokenLinks** that are **indexer false positives** from sealed session JSON text matching `..` and `"overview"` (session-20260805-maestro-knowledge-sync-*).
- Do **not** rewrite sealed session artifacts to "fix" these; root cause is LINK_RE over JSON/code contexts (upstream maestro-flow).
- knowledge audit typically **0 findings**; KG schema v6; prefer `maestro kg sync` after knowhow/docs land.
- Markdown wiki files under `.workflow/wiki/` are few; most wiki surface is projected from sessions/knowhow/specs.

## Commands
```bash
maestro wiki health
maestro knowledge audit --json
maestro kg sync
maestro kg health
maestro kg stats
```
