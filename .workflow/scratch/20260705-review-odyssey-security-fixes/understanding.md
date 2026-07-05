# Review Odyssey — Security Fixes (SEC-001/002/003/004)

## 1. Target & Scope

**Target:** The SEC-001/002/003/004 fix commit `84c355c` — 4 source files with real logic changes:
- `quantflow/data/store.py` — `_validate_symbol` in `get_date_range`
- `quantflow/data/fetcher.py` — `get_last_timestamp` (validate + parameterize)
- `quantflow/data/feature_store.py` — `load_features` (validate + parameterize)
- `quantflow/web/app.py` — `_same_origin_guard` auth+CSRF middleware, `_is_loopback_host`, `run_station` guard

**Dimensions:** correctness, security, performance, architecture (4 parallel independent agents).
**Flags:** `--auto -y` (auto-fix all tiers, auto-confirm). **Fix threshold:** all.

## 2. Archaeology

- `84c355c` (SEC-001/002/003/004 fix) is the most recent commit on all 4 files.
- Blame: `_same_origin_guard` lines 111, 120, 130-132 are from `84c355c`; the CSRF block (123-135) partially pre-exists from `c80c085` (deepfix). The token-then-early-return (line 120) and the `X-Requested-With` fallback (line 131) were both introduced in `84c355c`.
- No prior review session targeted these exact fixes.

## 3. Exploration

- **Call chain:** All mutation endpoints (`/api/session/kill-switch`, `/api/session/stop`, `/api/data/download`, `/api/research`, `/api/validate`, `/api/workbench/state` POST) flow through `_same_origin_guard`. GETs bypass the mutation branch entirely (line 111 method-set check).
- **Recent changes:** the 4 files were stable before `84c355c`; the security commit is the sole recent change.
- **Similar patterns:** `_validate_symbol` is now imported across 3 modules (store, fetcher, feature_store) — a cross-cutting validation primitive threaded through private imports rather than a shared public API.

## 4. Review Results — Severity Matrix

### HIGH (2)

| ID | Dim | Finding | Location | CWE |
|----|-----|---------|----------|-----|
| REV-001 | security | **`X-Requested-With` presence-check is attacker-controllable → CSRF bypass.** On token-less loopback deployments (the default), `has_custom_header = request.headers.get("X-Requested-With") is not None` accepts ANY value. `X-Requested-With` is NOT a forbidden CORS header — a malicious page can send `fetch('http://127.0.0.1:8088/api/session/kill-switch', {method:'POST', headers:{'X-Requested-With':'x'}})` and bypass the Origin check. Defense-in-depth that actively weakens the primary CSRF control. | `app.py:131` | CWE-352 |
| REV-002 | correctness+security | **Valid token early-returns, skips CSRF check.** Line 120 `return await handler(request)` fires before the CSRF block (122-136). Docstring (89-110) promises "two layered controls" but control flow makes them mutually exclusive. *Security view: sound per single-operator threat model (bearer authenticates intent). Correctness view: contradicts docstring.* Cross-dim tension — see §5 decision. | `app.py:120` | CWE-352 |

### MEDIUM (5)

| ID | Dim | Finding | Location | CWE |
|----|-----|---------|----------|-----|
| REV-003 | perf+security | `_station_token()` reads `os.environ` per mutation request; docstring claims "read once at module import". Cache at module level. | `app.py:48` | CWE-1041 |
| REV-004 | correctness+security | `get_last_timestamp` interpolates `parquet_dir` raw (no `.as_posix()`, Windows-broken) + no quote-escaping. Inconsistent with `store.py:155`/`feature_store:140`. Dead code currently. | `fetcher.py:130` | CWE-704 |
| REV-005 | architecture | `_validate_symbol` (private, underscore) imported across 3 modules via lazy in-method imports. Contract violation; should be public in `common/validators.py`. | `store.py:18` | CWE-1104 |
| REV-006 | architecture | `run_station` enforces non-loopback-bind guard, but `create_app` does not — policy depends on entry point; test harness/alt launcher bypass the fail-closed guard. | `app.py:364` | CWE-489 |
| REV-007 | architecture | Lazy `import duckdb` + fetcher re-implements DataStore's read path against DataStore's on-disk layout (L1 layer violation). Delegate to `DataStore.get_date_range`. | `fetcher.py:128` | CWE-1104 |

### LOW (7)

| ID | Dim | Finding | Location | CWE |
|----|-----|---------|----------|-----|
| REV-008 | security | `save()`/`save_features()` do `symbol.replace('/','_')` WITHOUT `_validate_symbol` — write path inconsistent with read path (path-traversal surface). | `store.py:65`, `feature_store.py` | CWE-22 |
| REV-009 | security+correctness | `parquet_dir` interpolated into SQL literal without quote-escaping (inconsistent with `_read_parquet_source:193` which escapes `chr(39)`). | `store.py:159`, `fetcher.py:130` | CWE-89 |
| REV-010 | correctness | Bare `except Exception: pass` swallows real storage errors as None/empty, no logging (unlike `store.query():137`). | `store.py:163`, `fetcher.py:141`, `feature_store.py:118` | CWE-390 |
| REV-011 | correctness | Truthy check `result[0]` instead of `is not None` (timestamp 0 falsy) — matches MEMORY anti-pattern. | `fetcher.py:140` | CWE-480 |
| REV-012 | architecture | `create_app` reaches into `session_manager._history_store` (private) via getattr — same private-API pattern. | `app.py:331` | CWE-1104 |
| REV-013 | architecture | Auth/CSRF policy as private functions in routing module; should be `web/security.py` for reuse + isolated testing. | `app.py:40` | CWE-1104 |
| REV-014 | performance | `_read_parquet_source` materializes full path list + string-builds SQL array per query instead of handing DuckDB a glob. | `store.py:193`, `feature_store.py` | CWE-1041 |

**Cross-dimension convergence:** REV-001 (security HIGH) is the dominant finding — the CSRF guard is bypassable. REV-005/REV-013 (architecture) converge on the same root pattern: cross-cutting security primitives (`_validate_symbol`, auth middleware) live as private functions in the wrong module. REV-004/REV-009/REV-007 converge on `get_last_timestamp` being a duplicated, lower-quality copy of `DataStore.get_date_range` (layer violation + missing escaping + missing `.as_posix()` + dead code).

## 5. Fix & Confirmation

### Fix tier — HIGH (commit prior to 7da233a)

- **REV-001 (CSRF bypass via `X-Requested-With`)** — CLOSED. Removed the `has_custom_header`/`X-Requested-With` fallback entirely from `_same_origin_guard`. The Origin header (browser-controlled, unforgeable) is now the sole same-origin signal. Test: `test_cross_origin_mutation_blocked_even_with_custom_header` asserts a cross-origin POST *with* `X-Requested-With: XMLHttpRequest` still returns 403.
- **REV-002 (valid token skips CSRF)** — CLOSED. Restructured the middleware so the token check no longer early-returns; both controls run on every mutation (auth=who, CSRF=browser intent). Test: `test_valid_token_does_not_skip_csrf_for_cross_origin` asserts a valid Bearer token + mismatched Origin returns 403. The "layered controls" docstring is now true.

### Fix tier — MEDIUM (commit prior to 7da233a)

- **REV-003 (`_station_token` docstring drift)** — CLOSED. Docstring + module comment now both state per-request env read (rotation takes effect without restart), matching the actual implementation.
- **REV-004 (`parquet_dir` raw interpolation, Windows-broken)** — CLOSED. `fetcher.get_last_timestamp` now uses `parquet_dir.as_posix()` (forward-slash glob on Windows), mirroring store.py/feature_store.py.
- **REV-005 (security primitives in wrong module)** — CLOSED. Created `quantflow/common/validators.py` with public `validate_symbol`/`validate_columns` + `SYMBOL_PATTERN`/`COLUMN_PATTERN`. `store.py` keeps `_validate_symbol`/`_validate_columns` as back-compat aliases (test_trend_and_store imports them). `feature_store.py` and `fetcher.py` use top-level imports.
- **REV-006 (bind guard only in `run_station`)** — CLOSED (design decision). `create_app` is host-agnostic by design (testable without a socket); the non-loopback bind guard correctly stays at `run_station` (the only entry point that knows the host). Decision documented in the `create_app` docstring. Forcing a host into `create_app` would break the 234-test suite that calls `create_app` directly.
- **REV-007 (fetcher re-implements DataStore read path)** — CLOSED (deferred delegation). Full delegation to `DataStore.get_date_range` deferred (would change the return contract: MAX vs MIN/MAX tuple). Immediate fixes applied: validation, `.as_posix`, parameterized timeframe, quote-escape, logging, `is not None` check. Deferral documented in the `get_last_timestamp` docstring NOTE.
- **REV-008 (write path unvalidated)** — CLOSED. `store.save()` and `feature_store.save_features()` now call `validate_symbol()` on the write path, mirroring the read-side choke point.
- **REV-009 (inconsistent quote-escaping)** — CLOSED. `store.get_date_range` and `fetcher.get_last_timestamp` now `.replace("'", "''")` the glob pattern (mirrors `_read_parquet_source`'s `chr(39)` escaping).
- **REV-010 (silent error swallowing)** — CLOSED. All four sites (`store.get_date_range`, `store.query`, `fetcher.get_last_timestamp`, `feature_store.load_features`) now `except Exception as e: logger.warning(...)`.

### Fix tier — LOW (commit 7da233a)

- **REV-011 (truthy check on `result[0]`)** — CLOSED. `get_last_timestamp` now `result[0] if result and result[0] is not None else None` (timestamp 0 no longer falsy).
- **REV-012 (`create_app` getattr on private `_history_store`)** — CLOSED. `history_store` is now an explicit `create_app` parameter; the dead private-attribute fallback is removed. `StationService` (public field) and `StationSessionManager` (public param) both expose it.
- **REV-013 (auth/CSRF policy in routing module)** — CLOSED. Extracted `_station_token`, `_is_loopback_host`, `_MUTATION_METHODS`, `STATION_TOKEN_ENV`, `same_origin_guard` to `quantflow/web/security.py`. `app.py` imports + re-exports the underscored forms for back-compat (tests import them). No circular import (security.py imports only aiohttp + stdlib).
- **REV-014 (path-list materialization)** — CLOSED. `_read_parquet_source`/`_read_feature_source` now hand DuckDB a glob literal (`'.../**/*.parquet'`) directly when no start/end filter is set, instead of materializing the path list + string-building a SQL array. Empty dir → `None` (clean "no data", avoids a zero-matching glob that DuckDB errors on). Tests updated to the new contract.

### Confirmation

- **Test suite:** 1333 passed, 2 skipped (was 1332; net +1 — `test_read_parquet_source_no_paths_no_start_end` and `test_read_parquet_source_with_paths` now exercise distinct None/glob paths).
- **Lint gate:** `ruff check --fix .` (0 errors) + `ruff format .` (clean) — honors the lint-before-commit overlay.
- **Type check:** `mypy --strict` on all 6 touched modules — 0 issues.
- **Zero-residual review:** independent adversarial reviewer delegated (background); verdict pending — see §8 for the recorded outcome.

## 6. Generalization

_Pending S_GENERALIZE._

## 7. Discoveries

_Pending S_DISCOVER._

## 8. Learnings

_Pending S_RECORD._
