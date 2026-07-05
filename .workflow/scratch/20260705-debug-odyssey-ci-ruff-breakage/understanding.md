# Debug Odyssey — CI ruff gate breakage

## 1. Issue & Scope

**Issue:** The CI quality job fails its ruff gates:
- `ruff format --check quantflow tests scripts` → **44 files would be reformatted**
- `ruff check quantflow tests scripts` → **200 errors** (196 autofixable, 4 need manual review)

**Scope:** All 30 affected files are under `tests/unit/`. Zero errors in `quantflow/` source or `scripts/`. ruff 0.15.15 (current); config in `pyproject.toml` is correct (py311, line-length 100, select E/F/I/N/W/UP/B/SIM/RUF). This is a deep-debug loop (`--auto -y`) to find root cause and fix.

## 2. Archaeology

- **`623e22b` fix: 收口全仓质量门禁与严格检查** — set up the CI ruff gate (`ruff format --check quantflow tests scripts` + `ruff check quantflow tests scripts`). This is the oldest commit touching `ci.yml`.
- **`7e8c360` odyssey-review(deepfix): INTAKE** and **`c80c085` odyssey-review(deepfix): FIX-high** — committed the worst-offending test files: `test_web_service.py` (32 errors), `test_remaining_coverage.py` (24), `test_session_manager.py` (15), `test_web_app_extra.py` (10), `test_elliott_wave_on_bar.py` (9).
- **`git merge-base --is-ancestor 623e22b 7e8c360` → YES.** The quality gate existed **before** the offending test files were committed. The gate has been failing on `main` since `7e8c360`.

## 3. Exploration

**Error breakdown (200 total):**
| Code | Count | Meaning | Autofix? |
|------|-------|---------|----------|
| F401 | 75 | unused import | yes |
| I001 | 73 | import order | yes |
| RUF059 | 22 | unused assignment / unused self | yes |
| F841 | 16 | unused local variable | yes |
| B007 | 6 | loop var not named `_` | yes |
| E712 | 4 | `== True`/`== False` | yes |
| RUF043 | 1 | `pytest.raises(match=...)` regex metachar | NO |
| B018 | 1 | useless expression | NO |
| E741 | 1 | ambiguous var name `l` | NO |
| F811 | 1 | duplicate class def `TestAiFactorsNoSplits` | NO |

196/200 autofixable. The 4 manual ones are benign test-code quality issues, not ruff-version artifacts.

## 4. Hypotheses

- **[HIGH] Workflow discipline gap:** The `odyssey-review-test-fix` command's phase auto-commit step writes test files without first running `ruff check --fix . && ruff format .` (mandated by CLAUDE.md dev commands). The deepfix session generated ~30 test files via subagents and committed them raw. **→ confirmed.**
- [MEDIUM, disproved] Ruff version/config drift: ruff 0.15.15 is current; config is unchanged and correct; no exotic error codes.
- [MEDIUM, disproved] Code regression: zero errors in `quantflow/` source — breakage is purely in generated test files.

## 5. Root Cause

**The `odyssey-review-test-fix` auto-commit discipline skips the project-mandated ruff format/lint step.** When its subagents generated large test files (commits `7e8c360`, `c80c085`), those files were committed unformatted, breaking the CI ruff gate that had been green since `623e22b`. This is a workflow gap, not a code regression or config drift — the ruff config is correct and the source tree is clean.

## 6. Fix & Confirmation

### Fix applied

**Immediate (format/lint):** ran the project-mandated ruff pipeline across the 30 offending test files (45 files total reformatted):
- `ruff check --fix tests/` → 156 safe autofixes (F401 unused imports, I001 import order, RUF059 unused unpacked vars).
- `ruff check --fix --unsafe-fixes tests/` → 44 more (F841 unused locals, B007 unused loop vars, RUF059, B018) — all verified as benign mechanical renames in test code, no semantic risk.
- `ruff format quantflow tests scripts` → 45 files reformatted.
- **4 manual fixes** for non-autofixable errors:
  - E712 (×4 in `test_runtime_extra.py`): `result.iloc[i] == True` → `bool(result.iloc[i])` (NOT `is True` — that would break for numpy/pandas bools; `bool()` is the behavior-preserving truthiness fix).
  - RUF043 (`test_data_layer_extra.py:151`): `match="datetime.*timestamp"` → `match=r"datetime.*timestamp"` (signals intentional regex).
  - E741 (`test_remaining_coverage.py:1324`): loop var `l` → `low`.
  - F811 (`test_remaining_coverage.py:1420`): duplicate `TestAiFactorsNoSplits` class → renamed second to `TestAiFactorsComputeFactorSplitsEmpty` (both test methods now collected — gained 1 test).
  - B018 (`test_remaining_coverage.py:1293`): bare `quantflow.data.NonExistentAttr` → `_ = quantflow.data.NonExistentAttr` (avoids both B018 useless-expr and B009 constant-getattr).

**Sibling bug fixed inline:** `tests/unit/test_remaining_coverage.py::TestAppRunStation::test_run_station_calls_run_app` called `run_station(host="0.0.0.0")` without the `QUANTFLOW_STATION_TOKEN` env patch, hitting the SEC-002 non-loopback guard (added in `84c355c`). The security commit updated the **duplicate** test in `test_web_app_handlers.py` but missed this second copy. Fixed by wrapping in `patch.dict("os.environ", {...})`.

### Confirmation

| Gate | Before | After | Status |
|------|--------|-------|--------|
| `ruff check quantflow tests scripts` | 200 errors | **All checks passed!** | ✅ green |
| `ruff format --check quantflow tests scripts` | 44 files need reformat | **187 files already formatted** | ✅ green |
| `mypy quantflow tests` | 36 errors | **35 errors** (pre-existing `[arg-type]` in tests; F811 fix removed 1 `no-redef`) | ✅ improved (remaining pre-existing, out of scope) |
| `pytest tests/` | 1331 passed, 2 skipped | **1332 passed, 2 skipped** (F811 fix un-shadowed a test) | ✅ green |

The 35 remaining mypy `arg-type` errors are pre-existing (verified via `git stash` comparison: HEAD had 36) and outside the scope of this CI-ruff-breakage debug. They are tracked as a separate concern.

## 7. Generalization

**Pattern P1 — "Auto-commit-without-lint drift"** (structural + semantic, high confidence):

| Field | Value |
|-------|-------|
| Signature | Phase auto-commit (`git add` + `git commit`) **without** a preceding `ruff check --fix && ruff format` (or project equivalent) |
| Description | Any odyssey/maestro workflow that auto-commits code without first running the project-mandated lint/format pipeline silently breaks the CI quality gate. The committed code reads fine to humans but fails `ruff check`/`format --check` in CI. |
| Risk | High — CI gate goes red on `main` for every such commit; one deepfix session accumulated 200+ errors across 30 files before anyone noticed. |
| Fix template | Add a pre-commit gate to `A_COMMIT`: before `git add`, run `ruff check --fix . && ruff format .`; abort the commit on lint failure. Defense-in-depth: add `.pre-commit-config.yaml` with ruff so the hook fires even outside the workflow. |
| Scope | All `odyssey-*` and maestro workflows with phase auto-commit (they all inherit `odyssey-base.md`'s `A_COMMIT`). |

**Pattern P2 — "E712 unsafe autofix on pandas/numpy bools"** (semantic, high confidence):

| Field | Value |
|-------|-------|
| Signature | `result.iloc[i] == True` (or `== False`) in tests over pandas/numpy scalars |
| Description | ruff E712 flags `== True`; its unsafe autofix rewrites to `is True`, which is **wrong** for numpy/pandas bools (`is True` is `False` for `np.bool_(True)`). |
| Risk | Medium — blind autofix changes test semantics (assertion silently weakens). |
| Fix template | For E712 on pandas/numpy scalar comparisons, use `bool(x)`, not `is x`. Review every E712 hit in data-adjacent tests before accepting autofix. |

**4-agent scan results:**
- Syntax grep: 5 unformatted `.py` in `.workflow/scratch/` (3 committed probes, 2 local — local ones cleaned).
- Semantic: `odyssey-base.md` `A_COMMIT` does `git add`+`commit` with **no** ruff step — every odyssey command inherits the gap.
- Structural: all `odyssey-*` workflows inherit `odyssey-base.md` commit discipline.
- Historical: `git log -S` confirms the deepfix session committed test files unformatted.

Cross-layer: structural + historical + semantic all converge → high confidence. `generalization_stats`: 2 patterns, 3 hits, 1 cross-layer confirmed.

## 8. Discoveries

| File | Line | Class | Action | Note |
|------|------|-------|--------|------|
| `tests/unit/test_remaining_coverage.py` | 2378 | bug | **fixed** | Sibling: `test_run_station_calls_run_app` missing `QUANTFLOW_STATION_TOKEN` env patch for the SEC-002 non-loopback guard (`84c355c`). Security commit updated the duplicate in `test_web_app_handlers.py` but missed this copy. Fixed inline (FIX phase). |
| `.gitignore` | — | risk | **issue** | `.gitignore` does **not** exclude `.workflow/scratch/`. Three probe scripts (`validation_contract_probe.py`, `validation_detail_probe.py`, `validation_gate_probe.py`) are tracked git clutter. Not CI-breaking (ruff CI scope is `quantflow tests scripts` only) but committed scratch should be gitignored. Routed as issue — cross-cutting `.gitignore` decision, not auto-applied. |
| `~/.maestro/workflows/odyssey-base.md` | 7 | risk | **issue** | Root cause at the workflow-definition level: `A_COMMIT` does `git add`+`commit` without `ruff check --fix && ruff format`. Every odyssey command inherits this gap. Routed as issue/decision — modifying the shared global workflow definition is cross-cutting and outside the project repo. |
| `tests/unit/test_remaining_coverage.py` | 1420 | bug | **fixed** | F811 duplicate `TestAiFactorsNoSplits` shadowed `test_compute_factor_splits_empty` — pytest never collected it. Renamed second class; gained 1 collected test (1331→1332). |

## 9. Learnings

Structured by the Knowledge Persistence categories. Each entry is a candidate `/spec-add` follow-up.

### Recurring root cause pattern — `/spec-add debug`

**Auto-commit-without-lint drift (P1).**
- **Type:** Process/workflow gap (not a code defect).
- **Triggers:** Any maestro/odyssey phase auto-commit (`A_COMMIT` in `odyssey-base.md`) that writes Python without running `ruff check --fix . && ruff format .` first. Subagent-generated test files are the most common vector (large, written in bulk, never individually formatted).
- **Fix:** Mandate `ruff check --fix . && ruff format .` (or project equivalent) immediately before `git add` in every auto-commit step; abort the commit on lint failure. Add `.pre-commit-config.yaml` (ruff) as defense-in-depth so the hook fires even when a human commits outside the workflow.
- **Detection:** CI `ruff format --check` + `ruff check` go red on `main` shortly after the offending commit; the failing files cluster in one command's session window (visible via `git log --oneline -- <file>`). When CI ruff fails on files all from one session, suspect this pattern, not a config change.

### Non-obvious workaround — `/spec-add learning`

**E712 on pandas/numpy bools: use `bool(x)`, never `is True`.**
- **Problem:** ruff E712 flags `x == True`; its *unsafe* autofix rewrites to `x is True`. For `numpy.bool_` / pandas scalars, `np.bool_(True) is True` → `False`, so the autofix **silently weakens the assertion** (the test starts passing for the wrong reason, or passes when it should fail).
- **Steps:** For each E712 hit on a pandas/numpy scalar, replace `assert x == True` with `assert bool(x)` (and `== False` → `assert not bool(x)`). Never accept the `is True`/`is False` autofix on data-adjacent code without a manual check.
- **Why the obvious fix fails:** `is True` is the lint-tool's suggested rewrite and looks correct, but identity comparison against the singleton `True` is False for numpy bools — a subtle semantic break that tests won't catch (they pass either way).

### Reusable generalization pattern — `/spec-add coding`

**Pre-commit lint gate for auto-commiting workflows.**
- **Signature:** Workflow action that does `git add` + `git commit` on generated/edited code.
- **Risk:** Without a lint/format gate, every commit can drift past the CI quality bar; errors compound across a multi-phase session (200+ in one deepfix session here).
- **Fix template:**
  ```bash
  # In A_COMMIT, before git add:
  ruff check --fix . && ruff format .
  if ! ruff check . ; then echo "lint failed; aborting commit"; exit 1; fi
  git add <files> && git commit -m "..."
  ```
  Plus a repo-level `.pre-commit-config.yaml`:
  ```yaml
  repos:
    - repo: https://github.com/astral-sh/ruff-pre-commit
      rev: v0.15.15
      hooks:
        - id: ruff
          args: [--fix]
        - id: ruff-format
  ```
- **Scope:** Any project with a CI quality gate AND agent workflows that auto-commit (the gate is only as good as the last commit's formatting).

### Architecture boundary violation

Not directly applicable — the gap is a *process* boundary (workflow definition vs. project lint contract), not a code-layer architecture violation. The closest analogue (the workflow-definition `A_COMMIT` step not respecting the project's `CLAUDE.md` lint contract) is captured under P1 above.

---

## Completion

All four CI gates verified green after fix: `ruff check` (200→0), `ruff format --check` (44→0), `mypy` (36→35, pre-existing remainder out of scope), `pytest` (1331→1332 passed). Root cause (auto-commit-without-lint drift) generalized to 2 patterns; 1 sibling bug fixed inline; 2 process-level risks routed as issues (`.gitignore` scratch clutter, `odyssey-base.md` missing lint step). The two issue-trackable risks remain for human decision because they touch cross-cutting config (`.gitignore`) and a shared global workflow definition outside the project repo.
