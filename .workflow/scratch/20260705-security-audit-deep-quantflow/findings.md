# Security Audit — QuantFlow (deep)

**Date:** 2026-07-05
**Tier:** deep (OWASP + dependencies + secrets + CI/CD + STRIDE + git history)
**Scope:** project root (`quantflow/`, `tests/`, `docker/`, `.github/`, config)
**Stack:** Python 3.11+, CCXT (OKX), aiohttp, pydantic, DuckDB+Parquet, Redis, prometheus-client
**Entry points:** 23 aiohttp HTTP endpoints (`quantflow/web/app.py`), Typer CLI (`quantflow/cli/main.py`)
**Auth model:** NONE (local-only tool, binds 127.0.0.1 by default; CSRF-only via `_same_origin_guard`)

## Severity Matrix

### CRITICAL (1)

| ID | Cat | Finding | Location | Remediation |
|----|-----|---------|----------|-------------|
| SEC-001 | A03 | **SQL injection via unvalidated symbol in `DataStore.get_date_range`** — `symbol.replace("/", "_")` only, no `_validate_symbol()`; inserted into DuckDB `read_parquet('{pattern}')` glob string. Reachable from web: `DataSourceTagRequest.symbol` (plain pydantic str, no regex) → `service.tag_data_source` → `store.get_date_range(request.symbol)`. A crafted symbol with a single quote breaks out of the glob string and injects arbitrary DuckDB SQL (incl. `read_csv_auto('/etc/passwd')` style local file disclosure). Sibling `query()` correctly calls `_validate_symbol` at line 106 — this method bypasses it. | `quantflow/data/store.py:150` | Call `_validate_symbol(symbol)` at the top of `get_date_range` (mirrors `query()`). Use parameterized execution for the glob. Verified: `_SYMBOL_PATTERN = ^[A-Za-z0-9/_-]{1,20}$` rejects quotes. |

### HIGH (3)

| ID | Cat | Finding | Location | Remediation |
|----|-----|---------|----------|-------------|
| SEC-002 | A01 | **No authentication on any of the 23 HTTP endpoints**, including live-trading controls (`/api/session/start`, `/api/session/stop`, `/api/session/kill-switch`, `/api/data/download`). Only `_same_origin_guard` (CSRF) exists. Default bind is 127.0.0.1 (mitigation), but `--host` is configurable to 0.0.0.0 with no guardrail. Any local process/user can start a live OKX session or activate the kill switch. | `quantflow/web/app.py:260` | Require a shared-secret token (env-derived) via `Authorization` header middleware on all mutation endpoints. Refuse non-loopback bind unless token configured. CLAUDE.md mandates kill-switch in live mode — pair with auth. |
| SEC-003 | A06 | **9 known CVEs in 2 dependencies** (pip-audit on `requirements-lock.txt`): **aiohttp 3.14.0** — 8 CVEs (CVE-2026-54273/4/5/6/7/8/9/80: TLS SNI bypass, pipelined-request DoS, cookie host-only loss, HTTP parser max_line_size bypass, digest-auth redirect leak, zip-bomb decompression, payload resource leak, websocket frame DoS) fixed in **3.14.1**; **cryptography 48.0.0** — bundled OpenSSL vuln (GHSA-537c-gmf6-5ccf) fixed in **48.0.1**. aiohttp is the web framework — directly network-exposed. | `requirements-lock.txt` | Bump `aiohttp>=3.14.1`, `cryptography>=48.0.1`; regenerate lockfile; add `pip-audit` step to CI (`ci.yml`). |
| SEC-004 | A01 | **`_same_origin_guard` bypassed when `Origin` header omitted** — guard only enforces when `Origin` present. Cross-site `<form>` POST and `fetch(no-cors)` omit Origin; any local non-browser client (curl) omits it entirely. Provides false sense of CSRF security, compounded by no auth (SEC-002). | `quantflow/web/app.py:57` | Require a CSRF token (double-submit) or a custom header (`X-Requested-With`) that triggers CORS preflight, on all mutations. Pair with SEC-002 auth. |

### MEDIUM (9)

| ID | Cat | Finding | Location | Remediation |
|----|-----|---------|----------|-------------|
| SEC-005 | A03 | SQL string interpolation in `FeatureStore.load_features` — `start`/`end` interpolated via f-string (typed int mitigates, but breaks the parameterized pattern `DataStore.query` established). | `quantflow/data/feature_store.py:97` | Use `?` placeholders + `params.append(int(start))`. |
| SEC-006 | A04 | **No rate limiting** on any endpoint. `/api/research` and `/api/validate` run expensive backtest/validation synchronously; `/api/data/download` triggers OKX fetches + parquet writes. Local/network DoS starves the trading event loop. | `quantflow/web/app.py:260` | Token-bucket middleware per-IP on mutation/compute endpoints; small worker queue for research/validate. |
| SEC-007 | A04 | **No input size limit on POST JSON bodies** (except workbench state at 64 KiB). aiohttp default `client_max_size` 1 MiB not tightened; `ResearchRequest.params` accepts arbitrary nested dicts. | `quantflow/web/app.py:101` | Set explicit `client_max_size` (e.g. 256 KiB) on `web.Application`; validate params depth. |
| SEC-008 | A09 | **`_redact_secrets` only covers OKX env vars** (`OKX_API_KEY`/`OKX_SECRET`/`OKX_PASSPHRASE`), not `TELEGRAM_BOT_TOKEN`, `LINE_CHANNEL_ACCESS_TOKEN`, `REDIS_PASSWORD`. Telegram URL is `https://api.telegram.org/bot{token}/sendMessage` (alerts.py:77) — a connection error echoing the URL persists the token to `last_error` → `/api/session` → `session_snapshots.jsonl`. | `quantflow/web/session_manager.py:98` | Extend redaction to all secret env vars + regex patterns (`r'bot\d{6,}:[A-Za-z0-9_-]{30,}'`); centralize a `SECRET_ENV_NAMES` registry. |
| SEC-009 | A09 | **`session.last_error` fallback bypasses `_redact_secrets`** — line 391 reads `TradingSession.last_error` directly (set unredacted in engine.py:417/452/520) when `runtime.last_error` is None. Raw data-feed exceptions (CCXT errors echoing apiKey, Redis URLs with creds) flow into snapshots unscrubbed. | `quantflow/web/session_manager.py:391` | Wrap fallback: `_redact_secrets(getattr(session, "last_error", "") or "")`. Apply redaction at the single sink (`_build_snapshot`). |
| SEC-010 | A10 | **SSRF sink in `AlertManager._send_webhook`** — POSTs to `self.webhook_url` with no scheme allowlist, no IP-range blocklist. Telegram URL is hardcoded (safe), but the generic webhook path is a pure SSRF sink if `webhook_url` is ever config-settable. | `quantflow/monitoring/alerts.py:112` | Validate `webhook_url` https-only + reject loopback/private/link-local IPs; never allow via `QUANTFLOW_` env override. |
| SEC-011 | A05 | **Verbose exception messages surfaced to clients** — `str(exc)` returned in 7 handlers. Service-layer `ValueError`s echo user-supplied `config_path`; `DataError`/`GatewayConnectionError` may embed internal paths, OKX error bodies, DuckDB text. | `quantflow/web/app.py:104` (+114/123/135/151/231/251) | Log full exc server-side; return generic message + correlation id. Apply `_redact_secrets` to all `str(exc)`. |
| SEC-012 | cicd | **Dockerfile runs as root** (no `USER` directive). Web API + CLI execute as root inside container; mounted host volumes (`../data`, `../config`) are root-writable. Any web-layer RCE → root → host data tampering. | `docker/Dockerfile:1` | Add non-root user (`addgroup`/`adduser` + `USER app` + chown); `security_opt: [no-new-privileges:true]`, `read_only: true` in compose. |
| SEC-013 | cicd | **docker-compose exposes Redis 6379 to host without auth** + **hardcodes `GF_SECURITY_ADMIN_PASSWORD=admin`** (Grafana). Unauthenticated Redis → cache poisoning of OHLCV bars feeding strategies; admin/admin Grafana → metrics/positions readable, dashboards tamperable. | `docker/docker-compose.yaml:38,79` | Bind Redis to `127.0.0.1` or internal-only; `requirepass ${REDIS_PASSWORD}`. `GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:?required}`. |

### LOW (11)

| ID | Cat | Finding | Location | Remediation |
|----|-----|---------|----------|-------------|
| SEC-014 | A03 | `DataFetcher.get_last_timestamp` SQL injection (f-string `symbol`+`timeframe`) — **dead code (no callers)**, latent only. | `quantflow/data/fetcher.py:120` | Delete or apply `_validate_symbol` + `TIMEFRAMES` allowlist. |
| SEC-015 | secrets | `.gitignore` excludes `.env`/`.env.local` but not `*.key`/`*.pem`/`*.p12` — a misplaced private key would be committed. | `.gitignore:23` | Add `*.key`, `*.pem`, `*.p12`, `*.pfx`, `secrets.yml`. |
| SEC-016 | A05 | No TLS termination on Station HTTP server (loopback plaintext by default). | `quantflow/web/app.py:302` | Document loopback-plaintext; optional `ssl_context`; refuse non-loopback without TLS. |
| SEC-017 | A05 | `run_station` accepts `--host 0.0.0.0` with no warning/guardrail (compounds SEC-002). | `quantflow/web/app.py:300`, `cli/main.py:1036` | Refuse non-loopback bind unless auth token configured. |
| SEC-018 | A08 | JSONL history lines parsed with `json.loads` + no schema validation (safe — no code exec; local-tamper only). | `quantflow/web/history.py:186` | Minimal schema validation + per-line size cap. |
| SEC-019 | A01 | `resolve_config_path` (CLI, allows absolute/traversal) is visually similar to `resolve_config_path_safe` (web) — maintainer footgun. Verified web uses the safe variant everywhere. | `quantflow/common/config.py:111` | Rename to `resolve_config_path_cli`; lint rule disallowing the unsafe import from `quantflow.web.*`. |
| SEC-020 | A09 | OKX order/cancel logged with `symbol` (web-influenced, not validated in execution path) + raw exc text. | `quantflow/execution/okx_gateway.py:95` | Validate `order.symbol` in `submit_order`; route exc through `_redact_secrets`. Add audit logs. |
| SEC-021 | A07 | No brute-force protection / session expiration; live session runs indefinitely; no operator identity recorded. | `quantflow/web/session_manager.py:130` | Record operator id; re-confirmation token for live mode after idle period. |
| SEC-022 | A04 | Predictable `session_id` (second-precision timestamp + 6 hex = 24 bits). Not a credential, but enumerable. | `quantflow/web/session_manager.py:434` | Full `uuid4` or `secrets.token_urlsafe`. |
| SEC-023 | cicd | CI actions pinned to floating tags (`@v4`/`@v5`), not SHAs; `release.yml` has `contents: write`. | `.github/workflows/ci.yml:19`, `release.yml:24` | SHA-pin actions; Dependabot for action bumps. |
| SEC-024 | cicd | Monitoring images use `:latest` (mutable). | `docker/docker-compose.yaml:53,73` | Pin to version tag or digest. |

## Phase Coverage

- **OWASP Top 10 (A01-A10):** all categories checked. Controls verified present: `resolve_config_path_safe` (web), `_same_origin_guard` (partial CSRF), `_redact_secrets` (incomplete), `_parse_limit`, `yaml.safe_load` everywhere, `DataStore.query` parameterized. Gaps: `get_date_range` bypasses validation (SEC-001), no auth (SEC-002).
- **Dependencies:** `pip-audit` on `requirements-lock.txt` → 9 CVEs in aiohttp + cryptography (SEC-003). Lockfile present (71 pinned packages — good).
- **Secrets:** `.env.example` clean (empty placeholders); `.env` not tracked; no real secrets in source/tests/YAML. Git history: no deleted `.env`/`.key`/`.pem`. Gaps: redaction coverage (SEC-008/009), `.gitignore` (SEC-015).
- **CI/CD:** `.github/workflows/ci.yml` + `release.yml` exist (no "no CI" finding). No `pull_request_target`. Issues: floating action tags (SEC-023), Docker root (SEC-012), Redis/Grafana defaults (SEC-013).
- **STRIDE:** (1) Spoofing — no auth, any local process impersonates the operator (SEC-002). (2) Tampering — unauthenticated Redis + parquet writes + SQL injection (SEC-001/013). (3) Repudiation — no operator identity in session/order logs (SEC-020/021). (4) Information Disclosure — verbose errors + incomplete redaction (SEC-008/009/011). (5) DoS — no rate limiting + aiohttp CVEs (SEC-003/006). (6) Elevation of Privilege — container root (SEC-012).
- **Git history archaeology:** `git log --all --diff-filter=D -- "*.env" "*.key" "*.pem"` → 0 deleted secret files. `git log -p -S "password"` → no committed secrets in history.

## Top Remediation Priorities

1. **SEC-001 (CRITICAL):** add `_validate_symbol(symbol)` to `get_date_range` — one-line fix closes the web-reachable SQL injection.
2. **SEC-003 (HIGH):** bump aiohttp→3.14.1, cryptography→48.0.1; add `pip-audit` to CI.
3. **SEC-002/004 (HIGH):** add shared-secret auth middleware + CSRF token; refuse non-loopback bind without auth.
4. **SEC-008/009 (MEDIUM):** centralize secret redaction at the snapshot sink; cover all secret env vars + regex patterns.
5. **SEC-012/013 (MEDIUM):** non-root Dockerfile; bind Redis loopback + requirepass; Grafana password from env.

## Summary

**24 findings** (1 critical, 3 high, 9 medium, 11 low). The critical finding (SEC-001, SQL injection via `get_date_range`) is web-reachable through `/api/data/tag-source` and `/api/data/download` and is a one-line fix (`_validate_symbol`). The high-severity dependency CVEs (aiohttp, cryptography) are directly exploitable given the network-exposed web layer. No real secrets are committed, but redaction coverage is incomplete. The system's threat model is "local single-operator tool" (loopback bind, no auth) — acceptable if enforced, but the configurable `--host` and missing auth guardrails mean a misconfiguration silently exposes live-trading controls.
