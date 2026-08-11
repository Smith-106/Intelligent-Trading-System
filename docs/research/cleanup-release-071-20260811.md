# Cleanup + release v0.7.1 receipt

**Date**: 2026-08-11  
**Version**: 0.7.1  

## Local cleanup

| Action | Result |
|--------|--------|
| `__pycache__` (non-venv) | removed |
| `.pytest_cache` / `.ruff_cache` | removed |
| `.workflow/tmp/*` | cleared (gitignore) |
| `data/` | **kept** (runtime, gitignored) |
| `.workflow/kg` / sessions | **kept** |
| tracked `dist/*.sha256` history | **kept** (not deleted) |
| untracked old wheels 0.2/0.4 | removed locally if present |

## Remote

- No force-push; no history rewrite
- Tag `v0.7.1` + optional GitHub Release
- quantflow-docs-demo: sync public-demo README version stamp if pushable

## Not done (out of scope)

- Deleting parquet / paper_replay evidence
- Sealing unrelated lifecycle-drift sessions (DEFER)
- Scheme C visibility changes

## Wiki / KG

| Check | Result |
|-------|--------|
| wiki health | **92/100** · entries 286 · broken **4** (legacy session relative links `..` / `"overview"` — sealed history, not rewritten) · orphans 0 |
| kg sync | **succeeded** · codegraph ~2886 nodes · integrity ok · status pass |
| knowledge audit | specs active 199 · knowhow 50 · no apply prune |

Broken link sources (DEFER — sealed sessions):
- `session-20260805-maestro-knowledge-sync-20260805-052529`
- run `...-003-wiki-manage`

