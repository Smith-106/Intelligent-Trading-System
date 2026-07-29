# QuantFlow — Tech Stack

> Mapper 1 (Tech Stack) report for the QuantFlow codebase documentation rebuild.
> Grounded in `pyproject.toml`, `requirements-lock.txt`, `README.md`, `AGENTS.md`,
> `.workflow/project.md`, the `docker/` stack, `.pre-commit-config.yaml`, and
> spot-reads of `quantflow/strategy/{ai_factors,rd_agent,sentiment}.py`,
> `quantflow/cli/main.py`, `quantflow/web/app.py`, `quantflow/strategy/__init__.py`.
> No source code was modified.

## Overview

QuantFlow is a personal / small-team Crypto quantitative trading system targeting
OKX. It covers the full loop research → backtest/validation → paper → live, built
on a self-designed six-layer architecture (L1 data → L2 indicators → L3 strategy →
L4 signal/risk → L5 execution → L6 monitoring) with an in-house event-driven
`TradingSession` engine that unifies backtest/paper/live.

Key engineering facts (verified):

- **Self-built backtest engine**: `BacktestEngine` is pure pandas/numpy. VectorBT
  is present only as a commented-out optional dep and is **not** used (numba
  incompatibility with Python 3.14+; see `pyproject.toml:17`).
- **No external engine library** for trading — `TradingSession` is the orchestrator.
- **Config-driven**: all strategy/risk/exchange params are YAML; API keys only
  from env vars.
- **Packaging**: Hatchling build backend, `quantflow` console script entry point.

## Languages

| Language | Requirement | Notes |
|----------|-------------|-------|
| Python | `>=3.11` (`pyproject.toml:10`) | ruff/mypy target `py311`; **Docker image runs `python:3.12-slim`** (`docker/Dockerfile:1`). |
| YAML | config only | strategy/risk/global config under `quantflow/config/`. |
| Dockerfile / Compose YAML | deployment | see Deployment. |
| Shell (bash) | CI & scripts | `.github/workflows/ci.yml`, `release.yml`, `scripts/`. |

Type hints are mandatory and checked with `mypy --strict` (`pyproject.toml:103-106`).

## Core Dependencies

Versions below show the `pyproject.toml` floor and the **actual pinned version**
from `requirements-lock.txt` (generated 2026-06-07 on a clean Windows wheel env).

| Package | pyproject floor | Locked (requirements-lock.txt) | Purpose |
|---------|-----------------|-------------------------------|---------|
| `ccxt` | `>=4.0` | `4.5.56` | OKX REST + WebSocket data/execution (async). L1/L5. |
| `optuna` | `>=3.6` | `4.9.0` | Bayesian hyper-parameter optimization (L3). |
| `duckdb` | `>=1.1` | `1.5.3` | Local analytical store, zero-copy Parquet queries (L1). |
| `pandas` | `>=2.2` | `3.0.3` | Core dataframe engine; backtest/indicators/features. |
| `numpy` | `>=1.26` | `2.4.6` | Vectorized numerics. |
| `scipy` | `>=1.12` | `1.17.1` | Statistical routines (risk metrics, validation). |
| `pyarrow` | `>=15.0` | `24.0.0` | Parquet read/write backing for DuckDB. |
| `pydantic` | `>=2.0` | `2.13.4` | `AppConfig` config model (v2). |
| `pyyaml` | `>=6.0` | `6.0.3` | YAML config loading. |
| `typer` | `>=0.12` | `0.26.7` | CLI framework. |
| `rich` | `>=13.0` | `15.0.0` | CLI rendering. |
| `redis` | `>=5.0` | `8.0.0` | Real-time cache / live data (L1). |
| `prometheus-client` | `>=0.20` | `0.25.0` | Metrics export (L6). |
| `scikit-learn` | `>=1.5` | `1.9.0` | ML models — `MLEnsembleStrategy` meta-labeling, factor importance. |
| `structlog` | `>=24.0` | `26.1.0` | Structured logging (L6). |
| `feedparser` | `>=6.0` | `6.0.12` | RSS ingestion for sentiment. |
| `aiohttp` | `>=3.14.1` | `3.14.1` | **QuantFlow Station** web backend (23 REST endpoints) + async HTTP. |
| `cryptography` | `>=48.0.1` | `49.0.0` | Crypto primitives; **pinned for GHSA-537c-gmf6-5ccf** (bundled OpenSSL). |

**Optional extras** (`pyproject.toml:37-41`):

- `talib` → `TA-Lib>=0.4` (indicators, optional alt to pure-pandas).
- `purgedcv` → `purgedcv>=0.0.10` (WFO/purged CV helper).
- `ml` → `qlib>=0.9`, `torch>=2.0`, `transformers>=4.30` (AI/ML, see AI/ML Stack).
- `all` → all of the above.

**Security-pinned deps** (with reason comments in `pyproject.toml:33-34`):
`aiohttp>=3.14.1` (CVE-2026-54273..54280: TLS SNI bypass / DoS / cookie-CSRF
bypasses) and `cryptography>=48.0.1` (bundled OpenSSL vuln).

**Notable removed/disabled**: `vectorbt` is commented out (`pyproject.toml:17`);
the project uses its own `BacktestEngine` instead.

## Build & Tooling

- **Build backend**: Hatchling (`pyproject.toml:1-3`). Source/wheel targets
  exclude caches, `.venv`, `.workflow`, `data`, `tests`, etc.
- **Console script**: `quantflow = quantflow.cli.main:app` (Typer app).
- **Packaging check**: `python -m build`; published lock = `requirements-lock.txt`.
- **Formatter/Linter**: `ruff` (target `py311`, line-length 100). Selected rule
  sets: `E,F,I,N,W,UP,B,SIM,RUF`; isort known-first-party `quantflow`
  (`pyproject.toml:92-101`).
- **Type checker**: `mypy --strict` (`python_version=3.11`), with
  `ignore_missing_imports` overrides for third-party libs (ccxt, duckdb, optuna,
  pandas, scipy, sklearn, torch, transformers, yaml, …) and relaxed error codes
  for `tests.*` (`pyproject.toml:103-136`).
- **Pre-commit**: `.pre-commit-config.yaml` runs `ruff-check --fix` and
  `ruff-format`, rev pinned to `v0.15.15` (kept in sync with installed ruff).
- **Dependency audit**: `pip-audit>=2.7` in `[dev]` extras.
- **CI**: `.github/workflows/ci.yml` and `release.yml` (GitHub Actions).

## Data & Storage

- **Columnar storage**: Parquet with **Hive partitioning** `symbol/year/month`
  (`store.py`), queried **zero-import** via DuckDB (`duckdb>=1.1`).
- **Real-time cache**: Redis `>=5.0` (`8.0.0` locked) for live ticks/cache;
  Redis 7+ required in deployment.
- **Feature Store**: `feature_store.py` provides **point-in-time-safe** feature
  engineering to prevent future-data leakage between research and live.
- **Multi-timeframe alignment**: `mtf_aligner.py`.
- **DuckDB + Parquet** is the analytical source of truth; `data/cleaner.py`
  performs future-leak validation.

## Deployment

`docker/docker-compose.yaml` defines a 4-service stack (all images pinned to a
fixed major tag, no `:latest`):

| Service | Image | Exposure | Notes |
|---------|-------|----------|-------|
| `quantflow` | built from `docker/Dockerfile` (`python:3.12-slim`, non-root `uid 1001`, `read_only: true`, `no-new-privileges`) | `127.0.0.1:${QUANTFLOW_HOST_PORT:-18000}:8000` | healthcheck `/metrics`; mem limit 512M. |
| `redis` | `redis:7-alpine` | `127.0.0.1:6379` | `requirepass` from env (fails fast if unset); loopback-only. |
| `prometheus` | `prom/prometheus:v3.2.1` | `127.0.0.1:9090` | mounts `prometheus.yml` + `alert_rules.yml`. |
| `grafana` | `grafana/grafana:11.5.2` | `127.0.0.1:3000` | admin password from `GRAFANA_ADMIN_PASSWORD` (fails fast if unset); sign-up disabled. |

- **Topology**: single host, all ports bound to loopback — the station is not
  reachable off-box without an explicit override.
- **Config**: `.env` (not committed) supplies OKX keys, `REDIS_URL`,
  `TELEGRAM_BOT_TOKEN`/`CHAT_ID`, `QUANTFLOW_REDIS_PASSWORD`,
  `GRAFANA_ADMIN_PASSWORD`.
- **Runtime entry**: `quantflow run --mode paper --interval 60` (Dockerfile CMD).
- **Provisioning**: Grafana dashboards/datasources auto-provisioned from
  `docker/grafana/provisioning/`.

## Quality & Security

- **Lint/format**: ruff (gated in pre-commit).
- **Types**: `mypy --strict` (strict mode, return-any warnings on).
- **Tests**: `pytest` + `pytest-asyncio` (`asyncio_mode=auto`), markers
  `slow` / `integration` / `live`. Coverage via `pytest-cov` with
  `fail_under = 70` and `show_missing` (`pyproject.toml:138-153`).
- **Audit**: `pip-audit` in dev extras.
- **Security constraints enforced by design**:
  - API keys only from env vars, never code/logs.
  - **Live mode forces Kill Switch** — cannot be disabled by config.
  - `common/validators.py` sanitizes symbol/column inputs (injection/path-traversal).
  - Web tier (`web/security.py`) enforces CSRF + Bearer auth + startup protection.
  - Dependency pins for `aiohttp`/`cryptography` address known CVEs.
  - Docker hardening: non-root, read-only rootfs, no-new-privileges, loopback-only
    published ports, secrets-fail-fast via `${VAR:?...}`.

## AI/ML Stack

| Component | Status | Evidence |
|-----------|--------|----------|
| **Meta-Labeling** | **Implemented** | `AIFactorEngine.meta_label()` (`ai_factors.py:77`); also used inside `MLEnsembleStrategy` (`ml_ensemble.py:280 compute_meta_labels`, `:357 _apply_meta_labeling`) with sklearn `GradientBoostingClassifier`. `AIFactorEngine` is exported from `strategy/__init__.py`. |
| **AIFactorEngine** (ML factor gen + feature importance) | **Implemented & exported** | `strategy/__init__.py:3,16` public export. Lazy sklearn usage. |
| **FinBERT sentiment** (`SentimentAnalyzer` + `NewsCollector`) | **Implemented, NOT integrated** | `sentiment.py` lazy-imports `transformers` (FinBERT `ProsusAI/finbert`), has tests, but is **not exported** from `strategy/__init__.py` and **not wired to a CLI command**. `transformers`/`torch` are optional `[ml]` deps only. |
| **Qlib RD-Agent factor mining** | **Planned (skeleton only)** | `rd_agent.py` is a callable skeleton; `quantflow ai rdagent` CLI exists but fails fast with an install hint when `qlib` is absent. Real RD-Agent CLI invocation is blueprint **E13-S1** (acceptance: 5+ factors with IC > 0.03). `qlib` is an optional `[ml]` extra. |

Summary:
- **Active / production-capable AI**: Meta-Labeling (via `AIFactorEngine` and the
  `MLEnsembleStrategy`), backed by scikit-learn.
- **Built but dormant**: FinBERT sentiment (no CLI/export path yet).
- **Planned**: Qlib RD-Agent automated factor mining (skeleton + CLI stub only).

---

*Generated by Mapper 1 (Tech Stack) — factual snapshot, no source modifications.*
