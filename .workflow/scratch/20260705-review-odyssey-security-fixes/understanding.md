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

_Pending S_FIX._

## 6. Generalization

_Pending S_GENERALIZE._

## 7. Discoveries

_Pending S_DISCOVER._

## 8. Learnings

_Pending S_RECORD._
