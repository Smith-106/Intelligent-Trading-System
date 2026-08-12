# Cleanup + release v0.7.2 (2026-08-12)

## Scope
- Engineering uplift ENG-UP-01..06 (integration, gitleaks, coverage 75, AGENTS parity, lock, fail-closed)
- L6 research GO panel export (sealed performance_panel SoT)
- Residual unit fixes (W14 path, L1 CVD layering, streak late-bind)
- Repo hygiene: tmp/cache purge, gitignore `.workflow/tmp-*`, no data/ delete, no force-push

## Version
- 0.7.1 → **0.7.2** (patch)

## Invariants
- promotion_eligible remains false for research export
- parity paper↔live only
- No live promote / no engine rewrite
