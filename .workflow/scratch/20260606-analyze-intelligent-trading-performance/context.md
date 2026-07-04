# Context: Intelligent Trading System Performance

**Date**: 2026-06-06
**Source**: Maestro analyze
**Scope verdict**: large

## Decisions

### Decision 1: Treat QuantFlow as a CLI-first trading system

- **Context**: The repository has no frontend runtime; performance work should focus on CLI workflows, offline research, runtime trading loop, data storage, monitoring, and tests.
- **Chosen**: Optimize Python CLI and trading-system internals.
- **Rejected**: Frontend/UI performance work.
- **Impact**: All follow-up tasks should use CLI, tests, benchmarks, and Prometheus metrics as evidence.

### Decision 2: Baseline reproducibility comes before optimization

- **Context**: `quantflow benchmark` exists but currently fails in this `.venv` because `quantflow.data` eagerly imports `RedisCache` while `redis` is absent. `scripts/check_env.py` also reports missing required `pyarrow` and `optuna`.
- **Chosen**: First restore environment and benchmark/test passability.
- **Rejected**: Optimizing code before the benchmark can run.
- **Impact**: Wave 1 must include dependency/import-boundary cleanup.

### Decision 3: Online strategy recomputation is the first code hot path

- **Context**: Local benchmark shows empty strategy at about 228890 bars/s, one real trend strategy at about 350 bars/s, and three real strategies at about 126 bars/s.
- **Chosen**: Build incremental `on_bar` strategy path while preserving vectorized `generate_signals(df)`.
- **Rejected**: Rewriting `TradingSession` first.
- **Impact**: Implementation should target strategy templates and shared indicator-state helpers before changing execution gateway logic.

## Constraints

### Locked

- Keep `TradingSession` as the unified orchestration boundary unless later evidence contradicts this.
- Preserve `generate_signals(df)` as the research/backtest API.
- Any incremental live/paper strategy path must have parity tests against vectorized signals.
- Do not require Redis for `DataStore` / `FeatureStore` import unless Redis is promoted to a required dependency.
- Performance evidence should be repo-owned: `quantflow benchmark`, pytest, and CLI commands.

### Free

- Implementation may use strategy-local rolling state, a shared rolling indicator helper, or a lightweight stateful indicator engine.
- Validation caching can be in memory first; persistent cache is optional.
- Split-level parallelism may use stdlib executors, joblib, or Optuna `n_jobs` if dependency and determinism tradeoffs are acceptable.
- Data append optimization may use batch files plus compaction, daily partitions, or DuckDB staging.

### Deferred

- Reintroducing VectorBT/Numba as the core backtest engine.
- Migrating from pandas to Polars.
- Tick-level HFT engine design.
- GPU acceleration for ML factors.
- Major data lake redesign beyond append/compaction improvements.

## Code Context

- `quantflow/strategy/engine.py:143` - sequential strategy loop in `TradingSession.on_bar()`.
- `quantflow/strategy/templates/trend_following.py:57` - event-driven `on_bar()` rebuilds state window.
- `quantflow/strategy/templates/trend_following.py:101` - full-window rolling calculations.
- `quantflow/strategy/validation/gate.py:54` - CPCV stage.
- `quantflow/strategy/validation/gate.py:91` - rolling WFO stage.
- `quantflow/strategy/validation/gate.py:108` - anchored WFO stage.
- `quantflow/strategy/validation/cpcv.py:114` - per-split CPCV loop.
- `quantflow/strategy/validation/wfo.py:311` - per-window WFO loop.
- `quantflow/data/store.py:72` - monthly partition read/concat/rewrite pattern.
- `quantflow/data/feature_store.py:76` - feature partition read/concat/rewrite pattern.
- `quantflow/cli/main.py:268` - `research()` does not push date range into `DataStore.query()`.
- `quantflow/cli/main.py:761` - benchmark imports data package path that currently fails without Redis.
- `quantflow/data/__init__.py:6` - eager `RedisCache` import.
- `scripts/check_env.py:26` - Redis marked optional while imports require it for package import.

## Implementation Scope

### Scope 1: Restore baseline commands

- **Objective**: Make `scripts/check_env.py`, `quantflow benchmark`, and `tests/unit/test_cli.py` pass in the documented environment.
- **Acceptance**:
  - `python scripts/check_env.py` is READY, or its required/optional categories match runtime behavior.
  - `python -m quantflow.cli.main benchmark --bars 500 --trials 2 --wfo-windows 2 --skip-subprocess --json` emits JSON.
  - `python -m pytest tests/unit/test_cli.py -q` passes.

### Scope 2: Online strategy hot path

- **Objective**: Remove full-window DataFrame rebuild and full rolling recompute from live/paper `on_bar()` for at least `trend_following`, then apply the pattern to other templates.
- **Acceptance**:
  - Signal parity tests compare incremental and vectorized outputs on deterministic fixtures.
  - 3 real strategies reach at least 2000 bars/s on the same 2000-bar synthetic benchmark.

### Scope 3: Validation performance

- **Objective**: Reduce duplicate signal generation and backtest work in CPCV/WFO.
- **Acceptance**:
  - Gate reports per-stage elapsed time.
  - Identical `(slice, params)` evaluations are cached inside one validation run.
  - Quick/profile validation mode exists for iterative research.

### Scope 4: Data and CLI scaling

- **Objective**: Reduce avoidable full history scans and monthly partition rewrites.
- **Acceptance**:
  - `research`, `optimize`, and `validate` push date/timeframe filters into `DataStore.query()`.
  - Incremental append benchmark exists for DataStore/FeatureStore.
  - `status` uses one bounded data-file scan and optional Docker check.

## Next Step

Recommended next command: `/maestro-plan --from analyze:ANL-001` or implement Wave 1 directly as a small fix.
