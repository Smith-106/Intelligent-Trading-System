# FT-002 — CLI

| Field | Value |
|-------|-------|
| **ID** | FT-002 |
| **Status** | active |
| **Phase** | Phase 1 complete |

## Requirements

None tracked in `.workflow/blueprint` (no SPEC/REQ files present).

## Components

| Component | Role |
|-----------|------|
| TC-008 (CliEntry) | cli — see tech-registry |

## Description

Typer + Rich CLI with 9 commands: download, research, optimize, validate, run, benchmark, ai (rdagent), station, status. Entry point: quantflow.cli.main:app. OKX creds loaded from env only via _load_gateway_config_from_env.

---

*Refreshed by codebase-refresh at 2026-08-05T05:39:39Z*
