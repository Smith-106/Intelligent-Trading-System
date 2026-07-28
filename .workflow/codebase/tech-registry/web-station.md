# TC-009 — WebStation

| Field | Value |
|-------|-------|
| **ID** | TC-009 |
| **Type** | web-presentation |
| **Features** | FT-008 (QuantFlow Station Web UI) |

## Code Locations

- `quantflow/web/app.py:238` — `create_app(*, service, session_manager, history_store)` (host-agnostic constructor, REV-006 contract docstring L246); `run_station(host, port)` (L290, bind-boundary launch guard L299); 23 routes registered L264-285
- `quantflow/web/security.py:70` — `same_origin_guard` middleware (CSRF + Bearer auth, `hmac.compare_digest`); `_is_loopback_host` (L53), `_station_token` (L39, per-request read)
- `quantflow/web/service.py:1` — `StationService` (app service layer; `ResearchRequest`/`ValidationRequest`/`DataDownloadRequest` Pydantic)
- `quantflow/web/session_manager.py:1` — `StationSessionManager` (background `TradingSession` lifecycle, telemetry MAX_TELEMETRY_POINTS=240, `_gateway_config_from_env` L33, `_redact_secrets` L88-102)
- `quantflow/web/history.py` — `StationHistoryStore` (JSONL persistence for research/validation/session history)
- `quantflow/web/rate_limit.py` — `RateLimiter` (in-memory token bucket, `_Bucket`), `rate_limit_middleware` (per-client throttling on mutating routes), `_client_key`
- `quantflow/web/static/` — `index.html`, `app.js`, `styles.css`, `favicon.svg` (SPA frontend); `fonts/` (`SpaceGrotesk-{Bold,Regular,SemiBold}.woff2` — self-hosted, no runtime CDN, ISS-UX-20260728)

## Exported Symbols

`DataDownloadRequest`, `DataSourceTagRequest`, `RateLimiter`, `ResearchRequest`, `SessionRuntime`, `SessionStartRequest`, `StationHistoryStore`, `StationService`, `StationSessionManager`, `ValidationRequest`, `create_app`, `format_data_source_label`, `rate_limit_middleware`, `run_station`, `same_origin_guard`

## Dependencies

- **Imports**: `common`, `data.store`, `monitoring`, `strategy.catalog`, `strategy.engine`, `strategy.research`. Reaches across all layers — presentation/integration layer.
- **Imported by**: `cli/main.py` (station command).

## Notes

- **23 REST endpoints** (app.py:264-285): overview, strategies, data (snapshot/download/seed-demo/tag-source), research+history, validate+history, workbench state (GET+POST), monitoring, execution, session (start/stop/events/history/kill-switch), static.
- **Bind-boundary launch guard** (REV-006): `run_station` enforces `if not _is_loopback_host(host) and not _station_token(): raise RuntimeError`. `create_app` is host-agnostic; tests construct `create_app()` directly.
- **CSRF + Bearer auth**: `same_origin_guard` applies to every mutating (POST/PUT/PATCH/DELETE) request. Two orthogonal controls: shared-secret Bearer (`_station_token`, per-request env read, `hmac.compare_digest` constant-time) + Origin-header CSRF (L117-129). Prior `X-Requested-With` acceptance removed (CSRF bypass vuln).
- **Per-request token read**: `_station_token` reads `QUANTFLOW_STATION_TOKEN` from env every request (not module-load cached) — allows rotation without restart.
- **Secret redaction**: `_redact_secrets` (session_manager.py:88-102) masks `OKX_API_KEY`/`OKX_SECRET`/`OKX_PASSPHRASE` values as `***REDACTED***` before persistence/logs.
- **ISS-036 path leak (fixed, CWE-200)**: `service.py` resolves request-supplied paths via `resolve_config_path_safe` only (L487); `resolve_config_path` is re-exported (L29) solely to keep test patches working. API responses no longer echo internal filesystem paths (abs path / drive root).
- **ISS-041 serialization (fixed)**: `_to_jsonable` (service.py:302) is a thin wrapper over `common.jsonable.to_jsonable` — single owner for JSON-safe conversion. Eliminated the 7-branch `service._jsonable` copy that had diverged from `session_manager._jsonable` (4-branch), closing pandas/numpy type-leakage across web + history.
- **ISS-UX-20260728 Web UX hardening (commit `4e32c24`)**: 11 issues fixed across the static frontend.
  - **(M4) `setHTML()` XSS choke-point** (`app.js:726`): single innerHTML audit-face — `setHTML(node, html)` is the only sanctioned innerHTML sink; `metricCard` string/label branches now escape via `escapeHtml`. Static guard `tests/unit/test_innerhtml_choke_point.py` greps `app.js` source to assert `setHTML` exists + escape wrap (mirrors `validate_symbol` single-audit-face discipline, arch spec).
  - **(H1) load\* error feedback**: 9 `load*` functions (loadOverview etc.) wrapped in try/catch → `showToast` + re-throw, so failures surface to the user and trigger the M5 poll-stall banner instead of silently swallowing.
  - **(M5) poll-stall banner**: poll failure one-shot toast debounce + `body[data-poll-stalled]` banner (`app.js:117`).
  - **(M1) bootstrap failure overlay**: full-screen overlay + retry button (`index.html`, `textContent` only — M4-safe, no innerHTML).
  - **(L2) version-pill degrade**: failure shows "版本未知" + `data-state=failed` (`app.js:10953`).
  - **(M2) self-hosted fonts**: `SpaceGrotesk` woff2 (3 weights) under `static/fonts/` + `--font-display` token (`styles.css`), eliminating runtime Google Fonts CDN.
  - **(M3) skip-link a11y**: `.skip-link` migrated `:focus` → `:focus-visible`.

*Auto-generated by codebase-refresh at 2026-07-25T00:00:00Z; drift-realign 2026-07-28 ISS-UX-20260728 加固 + fonts/ 登记*
