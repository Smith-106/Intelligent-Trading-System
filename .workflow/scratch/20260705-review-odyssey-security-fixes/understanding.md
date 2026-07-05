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
- **Zero-residual review:** independent adversarial reviewer (workflow-reviewer agent) returned **CONFIRMED** — all 14 findings closed with verifiable code evidence, 0 new defects introduced. Threat-model decisions ("valid token does not bypass CSRF", "absent Origin = allowed for non-browser clients") confirmed sound for the single-operator local-first model. Reviewer raised 4 non-blocking concerns (glob inclusivity nuance, fetcher's module-level duckdb connection, port-sensitive Origin comparison, missing focused `SYMBOL_PATTERN` rejection test); the last is actionable and will be added.

### Confirmation verdict

**CONFIRMED** — `remaining_actionable == 0`. S_CONFIRM → S_GENERALIZE.

## 6. Generalization

Five distinct generalizable patterns extracted from findings with severity ≥ medium.

### Pattern G1 — "Layered security controls made mutually exclusive by early-return"
- **Source findings:** REV-001 (HIGH), REV-002 (HIGH), REV-003 (MEDIUM, docstring drift)
- **Affected dimensions:** security, correctness
- **Signature:** a middleware/handler docstring promises "layered defense-in-depth" (multiple controls), but the implementation `return`s after the first passing control, making the others dead code. Worse: a control that consults an attacker-controllable header (`X-Requested-With`) as a same-origin signal *actively weakens* the primary control.
- **Risk:** the docstring advertises protection that doesn't exist; a bypass of one control bypasses all.
- **Fix template:** (1) remove attacker-controllable signals from same-origin checks (Origin is the only browser-unforgeable one); (2) ensure each control runs to completion — no early `return` past a control unless it rejected the request; (3) align the docstring with the actual control flow.
- **Scope:** any auth/CSRF middleware claiming layered controls.
- **Coding standard:** "Layered controls must all execute per request. A `return` after one control is only permitted on rejection. Same-origin signals must be browser-unforgeable (Origin), never attacker-controllable headers."

### Pattern G2 — "Cross-cutting security primitive lives as a private helper in a sibling module"
- **Source findings:** REV-005 (MEDIUM), REV-007 (MEDIUM, layer violation), REV-013 (LOW but same root)
- **Affected dimensions:** architecture, security
- **Signature:** a security choke point (symbol validation, auth policy) is defined as a `_private` function in one module and borrowed via in-method `from sibling import _private` across 2+ other modules. The underscore signals "module-private implementation detail" — the wrong contract for a security primitive imported across layers.
- **Risk:** inconsistent audit surface (callers may bypass by re-implementing); the borrowing module's import breaks silently if the underscore form is renamed; security review can't grep for a single public API.
- **Fix template:** move the primitive to a dedicated `common/` module as a public (no underscore) function with a docstring explaining why it's public; keep a back-compat alias at the old site if needed.
- **Scope:** any `from X import _private` where the private name enforces a security/validity invariant.
- **Coding standard:** "Security/validation choke points imported across layers MUST be public API in `quantflow/common/`. Underscored forms are module-private implementation details — wrong contract for cross-layer security."

### Pattern G3 — "Duplicated lower-quality copy of a layer-correct read path"
- **Source findings:** REV-004 (MEDIUM), REV-007 (MEDIUM), REV-009 (LOW, escaping)
- **Affected dimensions:** correctness, architecture, security
- **Signature:** a higher layer re-implements a lower layer's read path against the lower layer's on-disk layout (e.g., `fetcher` hand-rolling a DuckDB glob against `DataStore`'s partition layout). The copy drifts below the original's safety: missing `.as_posix()` (Windows-broken), missing quote-escaping (SQL-injection surface), missing logging, missing `is not None` checks.
- **Risk:** the duplicated path is the one that breaks on Windows, leaks SQL, or swallows errors — because it doesn't inherit the original's hardening.
- **Fix template:** delegate to the layer-correct owner; if delegation is deferred (contract mismatch), apply the same hardening (`.as_posix`, escaping, logging, `is not None`) to the copy immediately and document the deferral.
- **Scope:** any `read_parquet`/`read_csv_auto` query outside the layer that owns the on-disk layout.
- **Coding standard:** "Parquet reads belong to L1 (DataStore). Higher layers delegate; if they must re-implement, they inherit every hardening from the original, not a subset."

### Pattern G4 — "Write path skips the validation choke point the read path enforces"
- **Source findings:** REV-008 (MEDIUM→LOW), plus the discovered sibling in `service.py:tag_data_source` (§7)
- **Affected dimensions:** security
- **Signature:** the read path (`query`, `get_date_range`) calls `validate_symbol()`, but the write/transform path (`save`, `save_features`, or a service-layer direct `Path` construction) does `symbol.replace('/', '_')` bare. Asymmetric validation leaves a path-traversal surface on the less-traveled path.
- **Risk:** a caller that only writes (or only transforms in-place) bypasses validation entirely.
- **Fix template:** every code path that turns a user/operator symbol into a filesystem path OR a DuckDB glob must pass through the single validation choke point — read, write, and in-place transform alike.
- **Scope:** every `Path(...) / symbol_name` and every `read_parquet('...{symbol}...')`.
- **Coding standard:** "Symbol → path/glob conversion validates at EVERY site, not just reads. `validate_symbol()` is mandatory on write and in-place-transform paths, symmetric with reads."

### Pattern G5 — "Launch-time safety guard not inherited by alternative entry points"
- **Source findings:** REV-006 (MEDIUM→design decision)
- **Affected dimensions:** architecture, security
- **Signature:** a fail-closed guard (non-loopback bind requires a token) lives in the launcher (`run_station`) but not the app constructor (`create_app`). Test harnesses and alternative launchers that call `create_app` directly bypass the guard.
- **Risk:** a future launcher or test that binds to a non-loopback host via `create_app` + manual `web.run_app` silently exposes live-trading controls.
- **Fix template:** when the guard genuinely depends on a parameter the constructor doesn't receive (host), keep it at the bind boundary BUT document the contract explicitly in the constructor docstring, and add a `validate_bind_config(host, token)` helper the launcher calls so the guard logic is reusable and unit-testable in isolation.
- **Scope:** any app with a fail-closed launch guard (bind address, TLS, feature flag).
- **Coding standard:** "Launch-time guards that depend on bind-time parameters live at the bind boundary, with the contract documented in the app-constructor docstring. The guard logic is a reusable helper, not inline in the launcher."

## 7. Discoveries

Project-wide scan for sibling instances of the §6 patterns.

### Sibling scan results

| Pattern | Scan method | Hits | Classification |
|---------|-------------|------|----------------|
| G1 (layered controls / early-return) | grep `_same_origin_guard`, `return await handler` in middlewares | 0 sibling | safe (single middleware) |
| G2 (private security primitive borrow-in) | grep `from quantflow.*import.*_validate` | 1 hit: `tests/unit/test_trend_and_store.py:12` imports the back-compat alias | safe (test-only; alias is intentional back-compat) |
| G3 (duplicated read path) | grep `read_parquet(`, `read_csv_auto(` outside `data/` | 0 production sibling | safe |
| **G4 (write/transform path unvalidated)** | grep `symbol.*\.replace`, `Path\(.*symbol`, `parquet_dir.*symbol` | **1 hit: `web/service.py:1163` `tag_data_source`** | **risk — path traversal on HTTP endpoint** |
| G5 (launch guard) | grep `run_station`, `create_app` callers | 0 sibling launcher | safe |

### Confirmed sibling — `web/service.py:1163` (`tag_data_source`)

- **Pattern:** G4 (write/transform path skips validation choke point).
- **Site:** `tag_data_source(self, request: DataSourceTagRequest)` — handler for `POST /api/data/tag-source`.
- **Code:** `symbol_name = request.symbol.replace("/", "_")` → `symbol_dir = Path(config.data.parquet_dir) / symbol_name` → `symbol_dir.glob("*/*.parquet")`.
- **Request model:** `DataSourceTagRequest.symbol: str = "BTC/USDT"` — bare `str`, no validation constraint.
- **Failure scenario:** a request with `symbol = "../../etc"` (or any path-traversal payload) passes pydantic, reaches `Path(parquet_dir) / "..__etc"`, and globs an unintended directory. The downstream `store.query(request.symbol, ...)` calls would validate (DataStore choke point), but the **direct `Path` construction at line 1164 bypasses DataStore** and runs first.
- **Severity:** MEDIUM (HTTP-exposed, but single-operator local threat model + the endpoint is mutation-class so it already passes through `_same_origin_guard` token/CSRF checks; traversal is bounded to the parquet_dir parent in practice).
- **Action:** FIXED (cross_phase_loops=1, commit f26285b). Applied `validate_symbol(request.symbol)` at line 1163, mirroring the store.py/feature_store.py write-path fix. Added a focused 14-case `SYMBOL_PATTERN` rejection test (reviewer non-blocking concern, made explicit). Suite 1347 passed / 2 skipped; ruff clean; mypy edit-site clean (14 pre-existing unrelated errors in service.py predate this work).
- **Note:** the same `request.symbol` flows to `store.save(...)` / `store.query(...)` / `store.get_date_range(...)` elsewhere in the file — those are safe (DataStore validates). Only the direct `Path` construction at 1163-1164 is the hole.

## 8. Learnings

Knowledge persistence per the review Knowledge Persistence categories table. Each entry below is a candidate for `/spec-add` in the indicated category.

### Cross-dimension recurring pattern → `/spec-add review`

**P-G1: Layered security controls made mutually exclusive by early-return.**
- Affected dimensions: security, correctness (REV-001, REV-002, REV-003 converged across all 4 review dimensions).
- Coding standard: layered controls must ALL execute per request; a `return` after one control is only permitted on rejection; same-origin signals must be browser-unforgeable (Origin), never attacker-controllable headers (`X-Requested-With` is NOT a forbidden CORS header — any cross-origin fetch can set it).
- Detection: grep for `return await handler` inside middleware that claims "layered" / "defense-in-depth" in its docstring; grep for `X-Requested-With` in security middleware.

### Security finding → `/spec-add debug`

**S-G4: Write/transform path skips the validation choke point the read path enforces.**
- Vulnerability type: path traversal (CWE-22) + SQL injection via glob literal (CWE-89).
- Triggers: any `symbol.replace('/', '_')` followed by `Path(...) / symbol_name` or `read_parquet('...{symbol}...')` that does NOT pass through `validate_symbol()`. The read path validates; the write/in-place-transform path often doesn't. Discovered sibling: `web/service.py:1163` (HTTP-exposed).
- Fix approach: every symbol→path/glob conversion site calls `validate_symbol()` — read, write, AND in-place transform. The choke point is `quantflow.common.validators.validate_symbol` (public, not underscored).
- Detection: `grep -rn "symbol.*\.replace.*['\"]/[\"']" quantflow/` then verify each hit calls `validate_symbol` first.

**S-G2: Cross-cutting security primitive as a private (`_`) helper borrowed across modules.**
- Vulnerability type: inconsistent audit surface (CWE-1104) — callers may re-implement instead of importing, bypassing the invariant.
- Triggers: `from X import _private` where the private name enforces a security/validity invariant and is imported by 2+ modules.
- Fix approach: move to `quantflow/common/` as public API; keep a back-compat alias at the old site if tests import the underscored form.

### Architecture violation pattern → `/spec-add arch`

**A-G3: Higher layer re-implements a lower layer's read path against the lower layer's on-disk layout.**
- Violation: L1 (DataStore) owns parquet reads; `fetcher.get_last_timestamp` hand-rolled a DuckDB glob against DataStore's partition layout (L1→L3 layer violation).
- Correct boundary: higher layers delegate to `DataStore.get_date_range` / `DataStore.query`. If delegation is deferred (contract mismatch), the copy inherits EVERY hardening from the original (`.as_posix`, quote-escape, logging, `is not None`), not a subset.
- Verification: `grep -rn "read_parquet\|read_csv_auto" quantflow/` outside `quantflow/data/` — every hit should either delegate to DataStore or carry a deferred-delegation NOTE.

**A-G5: Launch-time safety guard not inherited by alternative entry points.**
- Violation: `run_station` enforces non-loopback-requires-token; `create_app` (test harness) doesn't.
- Correct boundary: when the guard depends on a bind-time parameter (host) the constructor doesn't receive, the guard lives at the bind boundary with the contract documented in the constructor docstring. The guard logic is a reusable `validate_bind_config(host, token)` helper, not inline in the launcher.
- Verification: grep launchers for inline guards; confirm the app-constructor docstring states the contract.

### Reusable generalization pattern → `/spec-add coding`

**R-G1: Middleware "layered controls" docstring must match control flow.** When a middleware docstring promises multiple controls, write a test that proves EACH control independently rejects its targeted attack (e.g. valid-token-still-blocked-by-CSRF; cross-origin-still-blocked-with-X-Requested-With). A docstring that drifts from control flow is a security lie.

**R-G4: Validate at every symbol→path/glob site, symmetric across read/write/transform.** The validation choke point is a single public function (`validate_symbol`); every conversion site calls it. Do NOT rely on "the downstream DataStore call validates" — a direct `Path` construction runs first.

### Non-blocking reviewer concerns (recorded, not actioned)

- Glob inclusivity: `**/*.parquet` is slightly more inclusive than the old `*/*.parquet` array (would match a stray depth-1 parquet). `DataStore.save()` never writes such files, so not a correctness regression; `union_by_name=true` handles schema merge. Worth a one-line comment if a future caller writes non-partitioned parquet into a symbol dir.
- `fetcher.get_last_timestamp` uses the module-level `duckdb.query` (shared global connection) rather than an instance `self._db`. Pre-existing; the function is currently uncalled dead code per its own docstring (REV-007 deferred delegation).
- Origin comparison is port-sensitive (`netloc` includes port). Correct for same-origin browser POSTs (matching Origin/Host ports); a reverse-proxy that rewrites Host without port could cause a false 403. Acceptable for the single-operator local threat model; document if deployment topology changes.
