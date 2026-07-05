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

_Pending S_FIX._

## 7. Generalization

_Pending S_GENERALIZE._

## 8. Discoveries

_Pending S_DISCOVER._

## 9. Learnings

_Pending S_RECORD._
