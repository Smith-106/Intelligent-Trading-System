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

_Pending S_GENERALIZE._

## 8. Discoveries

_Pending S_DISCOVER._

## 9. Learnings

_Pending S_RECORD._
