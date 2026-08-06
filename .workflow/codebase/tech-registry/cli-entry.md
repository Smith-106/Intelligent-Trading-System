# TC-008 — CliEntry

| Field | Value |
|-------|-------|
| **ID** | TC-008 |
| **Type** | cli |
| **Features** | FT-002 (CLI) |
| **Last Updated** | 2026-08-05T05:37:59Z |

## Code Locations

- `quantflow/cli/main.py`
- `quantflow/cli/services/__init__.py`
- `quantflow/cli/services/benchmark.py`
- `quantflow/cli/__init__.py`

## Exported Symbols

- `DEFAULT_CONFIG_PATH` — Default config file path
- `FUNDING_HISTORY_MAX_DAYS` — OKX funding-rate history window cap (90d)
- `ai`
- `benchmark`
- `download`
- `download_funding` — CLI: backfill funding-rate history from OKX (v0.4.0)
- `download_oi` — CLI: backfill open-interest history from OKX (v0.4.0)
- `optimize`
- `research`
- `run`
- `station`
- `status`
- `validate`

## Dependencies

- Upstream: `quantflow/common` (models, exceptions, config).
- Downstream consumers: see feature maps for consumer wiring.

---

*Refreshed by codebase-refresh at 2026-08-05T05:39:39Z*
