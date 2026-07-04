# Intelligent Trading System Performance Analysis

**Date**: 2026-06-06
**Scope**: QuantFlow / Intelligent-Trading-System 全方位性能研究
**Mode**: Maestro analyze, macro scope
**Recommendation**: CONDITIONAL GO，先修复性能基线可复现性，再按 P0/P1 分批优化

## Executive Summary

本次研究确认 QuantFlow 的主要性能问题不在 `TradingSession` 框架本身，也不在 `PaperGateway`，而在 3 类放大效应：

1. 在线策略路径每根 bar 都把窗口重建成 DataFrame，并对整个窗口重新 rolling/ewm 计算。实测空策略吞吐约 228890 bars/s，单个 `trend_following` 降到约 350 bars/s，3 个真实策略降到约 126 bars/s。
2. 离线验证 gate 会组合放大优化成本。默认 CPCV `C(8,2)=28` 路径，每条路径可再跑 `optimize_trials`，通过后还会跑 rolling 和 anchored 两套 WFO。
3. 数据与特征存储的增量写入采用“读整月分区，concat，去重，排序，重写 Parquet”，小批量追加时 IO 成本会随历史分区大小增长。

另外，当前本地 `.venv` 的性能基线不可完整复现：`scripts/check_env.py` 报告缺少 required `pyarrow` 和 `optuna`，`quantflow benchmark` 与部分 CLI 测试因 `redis` 缺失失败。`requirements-lock.txt` 已包含这些依赖，说明当前环境和 lock 文件不同步。

## Evidence Collected

### Local Baselines

| Area | Command / Scenario | Result |
|---|---:|---:|
| IndicatorEngine all indicators | 10000 rows | min 0.018309 s, avg 0.024348 s |
| IndicatorEngine all indicators | 100000 rows | min 0.096286 s, avg 0.099956 s, output 20.60 MB |
| BacktestEngine loop | 100000 rows | min 0.021147 s, avg 0.022569 s |
| BacktestEngine loop | 500000 rows | min 0.127308 s, avg 0.130448 s |
| Optimizer grid | 30 trials on 50000 rows | 0.441014 s |
| EventBus publish | 100k events, 0 handlers | avg 0.010402 s |
| EventBus publish | 100k events, 10 handlers | avg 0.091479 s |
| EventBus publish | 100k events, 50 handlers | avg 0.469282 s |
| CLI cold start | `python -m quantflow.cli.main --help` | min 0.905 s, avg 0.985 s |
| CLI status | `python -m quantflow.cli.main status` | min 0.890 s, avg 1.187 s |
| Runtime empty strategy | 2000 synthetic bars | 0.008738 s, 228890.6 bars/s |
| Runtime trend strategy | 2000 synthetic bars | 5.711069 s, 350.2 bars/s |
| Runtime 3 real strategies | 2000 synthetic bars | 15.908474 s, 125.7 bars/s |
| Paper order submit | 1000 paper orders | 0.012286 s, 81396.1 orders/s |

### Environment Findings

- `.venv` Python: 3.14.5.
- `scripts/check_env.py` result: NOT READY. Missing required `pyarrow` and `optuna`; `redis` shown as optional skip.
- `quantflow benchmark --bars 500 --trials 2 --wfo-windows 2 --skip-subprocess --json` failed with `ModuleNotFoundError: No module named 'redis'`.
- `pytest tests/unit/test_cli.py -q` failed 3 tests, all tied to `quantflow.data` package import requiring `redis`.
- `requirements-lock.txt` contains `pyarrow==24.0.0`, `optuna==4.8.0`, and `redis==8.0.0`.

## Findings

### P0-1: Online Strategy Path Recomputes Full Windows Per Bar

**Code facts**

- `TradingSession.on_bar()` synchronously loops all strategies and processes generated signals: `quantflow/strategy/engine.py:143`.
- `TrendFollowingStrategy.on_bar()` appends a bar, slices the list, calls `_bars_to_df()`, then calls `generate_signals(df)` for the whole window: `quantflow/strategy/templates/trend_following.py:57`, `quantflow/strategy/templates/trend_following.py:67`, `quantflow/strategy/templates/trend_following.py:71`.
- `TrendFollowingStrategy.generate_signals()` recomputes rolling/ewm indicators across the full window: `quantflow/strategy/templates/trend_following.py:101`, `quantflow/strategy/templates/trend_following.py:105`, `quantflow/strategy/templates/trend_following.py:115`, `quantflow/strategy/templates/trend_following.py:121`.
- The same pattern appears in `mean_reversion`, `volatility_breakout`, `momentum_rotation`, and `ml_ensemble`.

**Measured impact**

Empty strategy: 228890.6 bars/s.
One real trend strategy: 350.2 bars/s.
Three real strategies: 125.7 bars/s.

**Recommendation**

Keep `generate_signals(df)` as the vectorized research/backtest API, but add an incremental live/paper path:

- Use bounded `deque` or column arrays instead of rebuilding a DataFrame every bar.
- Maintain rolling state for MA, EMA, RSI, ATR, volume MA, Bollinger/Keltner windows.
- For strategies that still need DataFrame logic, compute only the last row from a shared window frame and avoid duplicate indicator calculation across strategies.
- Add a runtime benchmark test that asserts `TradingSession.on_bar` throughput for 3 real strategies does not regress.

**Acceptance target**

On the same 2000-bar synthetic benchmark, 3 real strategies should reach at least 2000 bars/s before broader refactors, while preserving signal parity against the current vectorized path on fixed fixtures.

### P0-2: Validation Gate Has Multiplicative Trial Cost

**Code facts**

- `validation_gate()` runs CPCV first, then rolling WFO, then anchored WFO: `quantflow/strategy/validation/gate.py:54`, `quantflow/strategy/validation/gate.py:91`, `quantflow/strategy/validation/gate.py:108`.
- CPCV default split count is `C(8,2)=28`: `quantflow/strategy/validation/cpcv.py:54`.
- Each CPCV split may optimize on train data and then recompute train/OOS signals and backtests: `quantflow/strategy/validation/cpcv.py:114`, `quantflow/strategy/validation/cpcv.py:142`, `quantflow/strategy/validation/cpcv.py:157`, `quantflow/strategy/validation/cpcv.py:182`.
- WFO has analogous per-window optimization and signal regeneration: `quantflow/strategy/validation/wfo.py:311`, `quantflow/strategy/validation/wfo.py:325`, `quantflow/strategy/validation/wfo.py:345`, `quantflow/strategy/validation/wfo.py:361`.

**Impact model**

With defaults, a gate can perform roughly `28 * optimize_trials + 2 * wfo_windows * optimize_trials` train-window optimization trials, plus signal generation and backtest passes. At `optimize_trials=50` and `wfo_windows=5`, this is about 1900 optimization evaluations before counting extra IS/OOS recomputation.

**Recommendation**

- Add staged validation modes: `smoke`, `profile`, `full`.
- Cache signal generation and backtest results by `(strategy, params, index-range, data-hash)`.
- Expose parallelism through `n_jobs` for Optuna and split-level job execution.
- Start with cheap prefilter trials, then run full CPCV/WFO only on top candidate parameter sets.
- Record validation runtime metrics per stage.

**Acceptance target**

For a fixed 5000-row dataset and fixed random seed, `validate --method gate --optimize-trials 10 --wfo-windows 5` should report per-stage elapsed times and avoid recomputing identical train slices with identical params.

### P0-3: Benchmark And Tests Are Blocked By Environment / Import Boundary

**Code facts**

- `quantflow/data/__init__.py` imports `RedisCache` eagerly: `quantflow/data/__init__.py:6`.
- `quantflow/data/redis_cache.py` imports `redis` at module import time.
- `scripts/check_env.py` treats `redis` as optional: `scripts/check_env.py:26`.
- `quantflow benchmark` imports `FeatureStore` and `DataStore`, which triggers the package import path and fails if `redis` is not installed: `quantflow/cli/main.py:761`.

**Observed failures**

- `quantflow benchmark ... --json` exits with `ModuleNotFoundError: No module named 'redis'`.
- `pytest tests/unit/test_cli.py -q` has 3 failures from the same import boundary.

**Recommendation**

- Either make Redis a required dependency everywhere, or make `RedisCache` import lazy/optional so data store and feature store commands do not require Redis.
- Align `scripts/check_env.py`, `pyproject.toml`, and `requirements-lock.txt`.
- Restore `quantflow benchmark` as the repo-owned performance gate before optimizing.

**Acceptance target**

`scripts/check_env.py`, `quantflow benchmark --bars 500 --trials 2 --wfo-windows 2 --skip-subprocess --json`, and `pytest tests/unit/test_cli.py -q` all pass in the documented local environment.

### P1-1: DataStore And FeatureStore Rewrite Whole Monthly Partitions

**Code facts**

- `DataStore.save()` groups by year/month, reads existing monthly Parquet, concatenates, de-duplicates, sorts, then rewrites: `quantflow/data/store.py:72`, `quantflow/data/store.py:76`, `quantflow/data/store.py:78`, `quantflow/data/store.py:88`.
- `FeatureStore.save_features()` follows the same read-concat-dedup-sort-write pattern: `quantflow/data/feature_store.py:71`, `quantflow/data/feature_store.py:76`, `quantflow/data/feature_store.py:77`, `quantflow/data/feature_store.py:79`.

**Recommendation**

- Buffer incoming bars/features and write larger batches.
- Consider daily or batch-id files under monthly partitions, then run periodic compaction.
- Keep current point-in-time correctness and duplicate removal semantics.
- Add append benchmark with increasing existing partition sizes.

### P1-2: CLI Research / Optimize / Validate Ignore Date Range Pushdown

**Code facts**

- `research()` exposes `start` and `end` parameters but calls `store.query(symbol)` without passing them: `quantflow/cli/main.py:245`, `quantflow/cli/main.py:268`.
- `optimize()` and `validate()` also load the full symbol history: `quantflow/cli/main.py:331`, `quantflow/cli/main.py:413`.
- `DataStore.query()` already supports `start`, `end`, `timeframe`, and projected columns: `quantflow/data/store.py:92`.

**Recommendation**

Convert CLI dates to millisecond timestamps and pass them into `DataStore.query()`. Add `--start`, `--end`, and `--timeframe` to optimize/validate where missing. Project only required columns when possible.

### P1-3: `status` Traverses Data Files Twice And Blocks On Docker

**Code facts**

- `status()` calls `any(data_dir.rglob("*.parquet"))`, then builds `list(data_dir.rglob("*.parquet"))` again: `quantflow/cli/main.py:1085`.
- Docker availability is checked via synchronous subprocess with a 5-second timeout: `quantflow/cli/main.py:1100`.

**Recommendation**

Use a single bounded scan or cached file count. Add a fast status mode that skips Docker. Keep deep environment checks in `scripts/check_env.py`.

### P1-4: Monitoring Lacks Data Loop Health Metrics

**Code facts**

- Existing metrics cover orders, signals, portfolio gauges, bar processing latency, and signal latency: `quantflow/monitoring/metrics.py:11`.
- `run_data_loop()` fetches bars, catches fetch errors, runs health checks, and sleeps, but does not expose fetch latency, last bar timestamp, reconnect count, or data error counter: `quantflow/strategy/engine.py:274`, `quantflow/strategy/engine.py:299`, `quantflow/strategy/engine.py:304`.

**Recommendation**

Add metrics for `data_fetch_latency_seconds`, `data_fetch_errors_total`, `last_bar_timestamp`, `session_running`, and `data_loop_iterations_total`. This separates “strategy generated no signals” from “data feed stalled”.

## Six-Dimension Scoring

| Dimension | Score | Confidence | Rationale |
|---|---:|---:|---|
| Feasibility | 4/5 | High | Most P0/P1 work is localized to strategy runtime, validation orchestration, import boundaries, and CLI query arguments. |
| Impact | 5/5 | High | Online runtime improves by orders of magnitude if per-bar full recompute is removed; validation and data IO optimizations reduce research cycle time. |
| Risk | 3/5 | Medium | Incremental indicators can introduce signal drift. Requires parity tests against vectorized path. |
| Complexity | 3/5 | Medium | Needs careful split between research API and live API, plus cache invalidation rules for validation. |
| Dependencies | 3/5 | High | Current environment dependency drift must be fixed first. No new external service is required for first wave. |
| Alternatives | N/A | Medium | Alternatives include reintroducing VectorBT/Numba for offline only, Polars/DuckDB feature pipelines, or keeping current architecture with benchmark-only gates. |

## Risk Matrix

| Risk | Probability | Impact | Mitigation |
|---|---:|---:|---|
| Incremental live indicators diverge from vectorized research signals | Medium | High | Golden parity fixtures per strategy and fixed synthetic regimes. |
| Validation caching returns stale results | Medium | High | Include data hash, index range, strategy name, params, fee, capital, and version in cache key. |
| Data partition layout migration breaks existing files | Low | Medium | Introduce append/batch mode behind config, keep reader compatible with current monthly files. |
| Dependency cleanup masks real missing runtime requirements | Medium | Medium | Align `check_env.py`, `pyproject.toml`, lock file, and CI tests in one change. |

## Recommended Execution Waves

### Wave 1: Restore Performance Baseline

1. Fix `quantflow.data` import boundary or require Redis consistently.
2. Sync local/dev dependency install with `requirements-lock.txt`.
3. Make `quantflow benchmark` pass and emit JSON in the standard environment.
4. Add `pytest --durations` or benchmark output to evidence.

### Wave 2: Online Runtime Throughput

1. Implement incremental `on_bar` path for `trend_following`, then generalize pattern.
2. Add shared rolling indicator helper or strategy-local state objects.
3. Prove signal parity on fixed fixtures.
4. Gate 3-strategy runtime benchmark.

### Wave 3: Offline Validation And Research Speed

1. Add staged validation modes.
2. Add signal/backtest cache for CPCV/WFO.
3. Add optional parallel execution.
4. Report per-stage validation runtime.

### Wave 4: Data IO And CLI Scaling

1. Add query pushdown for `research`, `optimize`, and `validate`.
2. Reduce DataStore/FeatureStore small-batch rewrite amplification.
3. Make `status` fast on large data directories.

### Wave 5: Monitoring And Deployment Performance

1. Add data loop health Prometheus metrics.
2. Add benchmark metrics to release/readiness evidence.
3. Improve Docker build cache and runtime image layering.

## Final Recommendation

Proceed, but do not start with a broad rewrite. The first implementation should restore reproducible performance baselines and then optimize the online strategy hot path, because local evidence shows the runtime bottleneck is strategy recomputation rather than the session engine or paper execution.
