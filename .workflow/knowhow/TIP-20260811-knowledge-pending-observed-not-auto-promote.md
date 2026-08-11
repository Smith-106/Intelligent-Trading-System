---
title: "Pipeline pending_observed is not auto-promote queue"
type: knowhow
tags: [knowledge, promote, wiki, tip]
status: active
related:
  - knowhow-doc-knowledge-hub
  - knowhow-tip-20260810-wiki-kg-false-positive-broken-links
---

# Pipeline pending_observed is not auto-promote queue

## Symptom

`maestro knowledge audit` may report large `pipeline.pending_observed` (hundreds) while recent sealed sessions show **all candidates promoted** via `maestro knowledge review <session>`.

## Cause

- Session ledgers retain historical `status=pending` rows, including duplicates and session-local decisions that never received promote receipts.
- Audit `pending_corroborated` can be **0** while `pending_observed` is large — only corroborated / reviewed items are safe to promote.
- Soft-prune plan may be empty when there is nothing **safe** to auto-apply (`--prune` yields no plan).

## Policy

1. For each **recent sealed** session: `maestro knowledge review <id>` → promote only `pending` with unique durable intent via `promote --resolve --as unique`.
2. Do **not** mass-promote old sessions’ pending blobs without human adjudication.
3. Prefer staging new durable knowhow/spec over replaying uncorroborated historical KDC rows.
4. Wiki `brokenLinks` for `..` / `\"overview\"` remain known false positives (do not rewrite sealed session JSON).

## Commands

```bash
maestro knowledge audit --scope all --json
maestro knowledge review <session-id> --json
maestro knowledge promote <session-id> --resolve <KDC-...> --as unique --reason "..."
maestro wiki health
maestro kg sync --json
maestro kg health --json
```
