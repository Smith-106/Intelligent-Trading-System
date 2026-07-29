# QuantFlow — Features & User-Facing Capabilities

**Mapper:** Mapper 3 (Features)
**Scope:** User-facing capabilities/features of the QuantFlow personal crypto quant
trading system (OKX). Grounded in source code under `quantflow/` (read directly),
plus `README.md` / `AGENTS.md` / `.workflow/project.md`. No source code was modified.

**Verification method:** Read actual implementations for every feature area
(strategies, CLI, research/validation/research pipelines, execution, risk, data,
web, indicators, AI). Status badges reflect code reality, not just docs.

---

## 1. Strategies — `ACTIVE`

**What it does:** Seven trading strategies share one dual-mode API
(`StrategyBase`): a vectorized `generate_signals(df) -> (entries, exits)` path for
research/backtest, and a stateful `on_bar(ctx, bar)` / `on_init` / `on_tick` path for
live/paper trading (signal emitted via `ctx.emit_signal`). Strategies are
YAML-driven and discovered through a shared catalog.

**Registered strategies (all wired into the catalog):**

| Strategy | Phase | File |
|---|---|---|
| `trend_following` | P1 | `quantflow/strategy/templates/trend_following.py` |
| `mean_reversion` | P1 | `quantflow/strategy/templates/mean_reversion.py` |
| `elliott_wave` | P1 | `quantflow/strategy/templates/elliott_wave.py` |
| `volatility_breakout` | P1 | `quantflow/strategy/templates/volatility_breakout.py` |
| `funding_rate` | P2 | `quantflow/strategy/templates/funding_rate.py` |
| `momentum_rotation` | P3 | `quantflow/strategy/templates/momentum_rotation.py` |
| `ml_ensemble` | P4 | `quantflow/strategy/templates/ml_ensemble.py` |

**Key points:**
- Catalog: `quantflow/strategy/catalog.py` — `get_strategy_factories()` /
  `get_strategy_specs()` / `load_strategy_config()` load per-strategy YAML from
  `quantflow/config/strategies/*.yaml` (all 7 YAML files exist).
- Base interface + dual-mode contract: `quantflow/strategy/base.py`
  (`StrategyBase`, `StrategyContext`). The docstring explicitly documents the
  two divergence classes between `generate_signals` and `on_bar` (regime gate +
  indicator-formula) — they are best-effort parity, not strict guarantees.
- `ml_ensemble` is active but requires a pre-trained `joblib` model
  (`model_path`); `on_init` loads it, and `generate_signals` returns empty signals
  until a model is trained via `train_model()`. It implements its own
  meta-labeling (triple-barrier `compute_meta_labels`) and does **not** use
  `AIFactorEngine`.
- All 7 are listed by `quantflow status` and selectable via `run --strategy` /
  `research --strategy` / `optimize --strategy` / `validate --strategy`.

---

## 2. CLI — `ACTIVE`

**What it does:** Typer + Rich command-line interface exposing the full workflow
download → research → optimize → validate → run, plus benchmark, ai, station, status.

**Commands (entry: `quantflow/cli/main.py`):**
- `download` — fetch OHLCV from OKX via `DataFetcher` → `clean_ohlcv` → `DataStore`.
- `research` — run `BacktestEngine` for a strategy and print a markdown report.
- `optimize` — run `StrategyOptimizer` (bayesian/cmaes/grid) over the strategy's
  param space; prompts the next step (`validate --method gate`).
- `validate` — anti-overfitting validation; `--method` = `cpcv | dsr | pbo | wfo |
  full | gate | lookahead | stress`.
- `run` — `TradingSession` in `paper | sandbox | live` mode (comma-separated
  multi-strategy supported).
- `benchmark` — synthetic performance baseline (data/indicators/research/
  validation/runtime/execution throughput, with optional threshold gates).
- `ai` — currently only `rdagent` (Qlib RD-Agent factor mining, with dependency
  guard); see AI layer.
- `station` — launch QuantFlow Station web UI (`run_station`).
- `status` — system status table (version, phase, data/indicators/strategies/
  validation/risk/gateway/kill-switch/monitoring).

**Key files:** `quantflow/cli/main.py` (all command definitions + display helpers);
`quantflow/strategy/catalog.py` (strategy discovery); `quantflow/common/config.py`
(`load_config`, `AppConfig`).

---

## 3. Research Pipeline — `ACTIVE`

**What it does:** Pure vectorized backtesting and parameter optimization replacing
the original VectorBT dependency (incompatible with Python 3.14+/numba).

- **`BacktestEngine`** (`quantflow/strategy/research/backtest.py`): vectorized
  long/short backtest on whole-bar entries/exits with fee model; outputs
  `BacktestResult` (Sharpe/Sortino/Calmar/MaxDD/win-rate/profit-factor/trades +
  `equity_curve`, `drawdown_curve`, `trade_returns`). Bar-frequency is inferred
  for correct intraday annualization. This is the engine used everywhere
  (research, CPCV, WFO, MC stress).
- **`StrategyOptimizer`** (`quantflow/strategy/research/optimizer.py`): Optuna
  samplers for `bayesian` (GPSampler w/ TPESampler fallback),
  `cmaes` (CmaEsSampler), and a deterministic local `grid` search; objectives
  sharpe/sortino/calmar/return/win_rate.
- **Report generation** (`quantflow/strategy/research/report.py`): `generate_report`
  → text or markdown summary of `BacktestResult`.

**Status:** fully implemented and active. No VectorBT dependency remains.

---

## 4. Anti-Overfitting Validation — `ACTIVE`

**What it does:** A layered validation suite to gate deployment on genuine edge
rather than backtest overfitting. All under `quantflow/strategy/validation/`.

- **CPCV** (`cpcv.py`): Combinatorial Purged CV (de Prado) with embargo periods;
  generates C(n_groups, n_test_groups) paths, optionally re-optimizes on train
  windows via Optuna, computes **PBO** and OOS efficiency. `passed` when `pbo < 0.5`.
- **DSR** (`dsr.py`): Deflated Sharpe Ratio, `passed` when `dsr > 0.95` (uses best
  OOS Sharpe from CPCV paths; fail-closed if no finite OOS Sharpe).
- **PBO** (`pbo.py`): stand-alone Probability of Backtest Overfitting.
- **WFO** (`wfo.py`): Walk-Forward Optimization, rolling + anchored; `passed` when
  OOS efficiency `> 0.5` (50%) for both modes.
- **GO/NO-GO gate** (`gate.py`): `validation_gate()` runs CPCV → DSR → WFO in
  sequence; all must pass for `GO`. This is the unified pipeline CLI `--method gate`.
- **Triple-barrier labeling** (`barriers.py`): `triple_barrier_labels()` (profit /
  stop / time) + `minimum_track_record_length()` for Sharpe confidence.
- **Look-ahead detection** (`lookahead.py`): static AST scan of `generate_signals`
  / `on_bar` for masked-aggregation patterns (`series[mask].mean()` etc.) that leak
  future bars — no data/backtest required. CLI `--method lookahead`.
- **Monte Carlo stress** (`monte_carlo.py`): `monte_carlo_stress()` runs two
  *diagnostic* resampling strategies — `trade_shuffle_stress` (permute trade-order)
  and `returns_bootstrap_stress` (bootstrap bar returns) — to bound worst-case
  drawdown/terminal return. Explicitly **non-gating** (does not alter GO/NO-GO).
- **Signal quality** (`signal_quality.py`): precision/recall/hit-rate/brier/OOS
  Sharpe metrics surfaced in every validation display.

**Status:** complete and active. All exposure thresholds (PBO<0.5, DSR>0.95,
WFO OOS>50%) match the spec.

---

## 5. Execution — `ACTIVE`

**What it does:** Order routing and fill management across three run modes with a
fail-closed emergency stop.

- **Run modes** (`quantflow/cli/main.py` `run` + `quantflow/execution/engine.py`
  `ExecutionEngine.start`): `paper` (local `PaperGateway`, no API key),
  `sandbox` (OKX testnet, `sandbox=True`), `live` (OKX real, `sandbox=False`).
- **`GatewayBase`** (`quantflow/execution/gateway_base.py`): ABC with
  `connect / send_order / cancel_order / query_positions` (abstract) and
  `disconnect / cancel_all_orders / update_market_price / subscribe`. Introduces
  `GatewayError` so callers (KillSwitch) can distinguish "failed query" from
  "genuinely empty".
- **`ExecutionEngine`** (`quantflow/execution/engine.py`): orchestrates kill-switch
  gate → route → track → metric → event → fill; integrates with EventBus
  (ORDER/FILL); `submit`/`submit_order`/`cancel`/`close_position`/`sync_positions`
  (fail-closed on `GatewayError`).
- **`OrderRouter`** (`quantflow/execution/order_router.py`): gateway dispatch +
  `build_order` / `build_close_request` (reduceOnly) — extracted from the engine.
- **`OrderManager`** (`quantflow/execution/order_manager.py`): order lifecycle +
  timeout tracking.
- **`KillSwitch`** (`quantflow/execution/kill_switch.py`): on `activate()` cancels
  all orders, flattens positions with reduceOnly market orders, blocks new
  submissions; fail-closed (reports `failed`/`partial` if query_positions raises).
- **OKX credentials from env only:** `quantflow/cli/main.py`
  `_load_gateway_config_from_env` reads `OKX_API_KEY` / `OKX_SECRET` /
  `OKX_PASSPHRASE` for sandbox/live; raises if missing.
- **Gateways:** `quantflow/execution/okx_gateway.py` (CCXT async, spot/swap,
  reconnect) and `quantflow/execution/paper_gateway.py` (local simulation).

**Status:** complete and active.

---

## 6. Risk Controls — `ACTIVE`

**What it does:** Multi-layer pre-trade risk gating and position sizing, wired in
`TradingSession` (`quantflow/strategy/engine.py`): per signal → `RiskEngine.check`
→ `PositionSizer.size` → `ExecutionEngine.submit_order(PositionRequest)`.

- **`RiskEngine` 7-check short-circuit** (`quantflow/signal/risk_engine.py`):
  tuple `(position_limit → portfolio_limit → strategy_budget → daily_loss →
  weekly_loss → drawdown → VaR)`; first failing check returns `RiskDecision(
  passed=False)` and aborts. `_check_var` uses historical CVaR (ES) gate, with a
  cached percentile recompute.
- **Half-Kelly sizing** (`quantflow/signal/position_sizer.py`): `PositionSizer`
  (`kelly_fraction=0.5` default) → `size()` returns order notional scaled by
  signal strength + strategy allocation, clamped by `max_position_pct`, with
  optional vol-targeting cap (opt-in) and fee deduction. (Note: the spec's
  "ScalingPositionSizer" name does not exist in code — the class is
  `PositionSizer`; it emits a notional that the session turns into a
  `PositionRequest`, not a separate `ScalingPositionSizer` step.)
- **VaR / CVaR** (`quantflow/signal/risk_metrics.py`): `value_at_risk` (historical
  default; parametric retained only as reference), `conditional_var` (ES),
  `bootstrap_cvar` (diagnostic CI on the point estimate), `max_drawdown`,
  `sharpe/sortino/calmar`.
- **Drawdown circuit breaker:** `_check_drawdown` vs `max_drawdown` config limit
  (part of the 7-check chain).
- **KillSwitch:** see Execution section (shared instance injected into
  `ExecutionEngine` + `TradingSession`).

**Status:** complete and active.

---

## 7. Data Layer — `ACTIVE`

**What it does:** Ingestion, storage, feature management, and leak-safe utilities.

- **CCXT async OKX fetcher** (`quantflow/data/fetcher.py`): `DataFetcher` with
  `connect`/`fetch_ohlcv` (pagination, non-finite bar rejection at parse boundary,
  per-call `CALL_TIMEOUT`), plus WebSocket (`watch_ohlcv`) / REST-poll streaming
  (`stream_bars`). Sandbox mode supported.
- **Parquet Hive + DuckDB** (`quantflow/data/store.py`): `DataStore` saves
  OHLCV as Hive-partitioned Parquet `symbol/year/month` (zstd), queries via
  DuckDB `read_parquet` with symbol/timeframe validation (path-traversal + SQL
  injection guards), append-fast path, fail-closed query errors.
- **FeatureStore (point-in-time safe)** (`quantflow/data/feature_store.py`):
  `compute_features(symbol, timestamp, …)` queries raw store with `end=timestamp`
  so no future data leaks; `save_features`/`load_features` mirror the Hive layout.
- **RedisCache** (`quantflow/data/redis_cache.py`): ticker/bar caching with TTL;
  raises `DataError` when unconnected (distinguishes connection failure from miss).
- **MTFAligner** (`quantflow/data/mtf_aligner.py`): multi-timeframe alignment
  (1W→4H→1H→15m) with **leak-safe** HTF shift (bar-open → bar-close visibility)
  so higher-timeframe values only become visible after the HTF bar closes.
- **`clean_ohlcv` / `validate_no_future_leak`** (`quantflow/data/cleaner.py`):
  dedup, gap-fill, OHLC-relationship repair, outlier z-score handling, and
  future-timestamp rejection (raises `ValueError` on leak).

**Status:** complete and active; leak-safety is explicitly engineered at every
layer (fetch parse, store query, feature compute, MTF align, cleaner).

---

## 8. QuantFlow Station Web UI — `ACTIVE`

**What it does:** A local-first aiohttp control surface for the whole system.

- **Framework:** `quantflow/web/app.py` (`create_app` / `run_station`), aiohttp,
  served from `quantflow/web/static/` (SPA).
- **Endpoints (verified: 21 API routes + index + static asset route; docs cite 23)
  across 9 groups:**
  - overview — `GET /api/overview`
  - strategies — `GET /api/strategies`
  - data — `GET /api/data`, `POST /api/data/download`, `POST /api/data/seed-demo`,
    `POST /api/data/tag-source`
  - research — `POST /api/research`, `GET /api/research/history`
  - validate — `POST /api/validate`, `GET /api/validate/history`
  - workbench — `GET|POST /api/workbench/state`
  - monitoring — `GET /api/monitoring`
  - execution — `GET /api/execution`
  - session — `GET /api/session`, `GET /api/session/events`,
    `GET /api/session/history`, `POST /api/session/start`,
    `POST /api/session/stop`, `POST /api/session/kill-switch`
- **Security:** `quantflow/web/security.py` `same_origin_guard` middleware applies
  two orthogonal controls to all mutation methods (POST/PUT/PATCH/DELETE):
  (1) Bearer shared-secret auth via `QUANTFLOW_STATION_TOKEN` (constant-time
  `hmac.compare_digest`), (2) CSRF Origin↔Host match; `X-Requested-With` is
  explicitly **not** trusted (historical bypass removed). Read-only GETs exempt.
- **Bind-boundary launch guard:** `run_station` refuses to bind a non-loopback
  host without `QUANTFLOW_STATION_TOKEN` (raises instead of silently exposing
  live-trading controls).
- **Defense extras:** 256 KiB body cap, per-IP rate-limit middleware, path/secret
  redaction at the HTTP boundary (`_redact_paths`), error responses scrubbed via
  `redact_secrets`.

**Status:** complete and active.

---

## 9. Indicators — `ACTIVE`

**What it does:** A pure pandas/numpy indicator library (no external TA dependency)
plus a market-regime detector for strategy gating.

- **`IndicatorEngine`** (`quantflow/indicators/engine.py`): `batch_calculate` /
  `compute_all`; `FACTOR_NAMES` enumerates **27 factors**:
  - Trend (7): `sma_20, sma_50, ema_12, ema_26, macd, macd_signal, macd_histogram`
  - Momentum (4): `rsi_14, stoch_k, stoch_d, williams_r_14`
  - Volatility (5): `atr_14, bb_upper, bb_middle, bb_lower, adx_14`
  - Volume (5): `obv, vwap, mfi_14, volume_sma_20, volume_ratio`
  - Elliott Wave (6): `zigzag_pivots, wave_count, fibonacci_levels,
    critical_levels, wave_channel, divergence`
  - Implementations: `quantflow/indicators/{trend,momentum,volatility,volume}.py`
    + `{zigzag,wave_identifier,fibonacci,critical_level,wave_channel,divergence}.py`;
    registered via `quantflow/indicators/base.py` registry.
- **`MarketRegimeDetector`** (`quantflow/indicators/regime.py`): ADX-based
  trending vs mean-reversion classification (+ BB-width / ATR-percentile); used by
  `TradingSession` to gate strategies by `required_regime` (`on_bar` path only; the
  vectorized `generate_signals` path is intentionally not regime-gated — documented
  divergence in `base.py`).

**Status:** complete and active (21 base + 6 Elliott = 27).

---

## 10. AI Layer — `MIXED (partial)`

**What it does:** ML/meta-labeling, sentiment, and automated factor mining — uneven
maturity across the three sub-components.

- **`AIFactorEngine` (Meta-Labeling) — EXPORTED but NOT integrated.**
  `quantflow/strategy/ai_factors.py` provides `meta_label` / `compute_factor` /
  `feature_selection` (sklearn RandomForest / GradientBoosting / mutual-info). It
  IS listed in `quantflow/strategy/__init__.py` `__all__`, but **no strategy or CLI
  command calls it** — `MLEnsembleStrategy` ships its own internal meta-labeling
  instead. Effectively a standalone library, not wired into the pipeline.
- **`MLEnsembleStrategy` — ACTIVE** (`quantflow/strategy/templates/ml_ensemble.py`):
  uses the 21 factors as features with a GradientBoosting primary model + a
  meta-labeling filter (triple-barrier labels), expanding-window OOS training, and
  fail-closed reject-all if the meta-model errors. Registered in the catalog
  (`ml_ensemble`). Requires a trained `joblib` model to emit signals.
- **FinBERT sentiment — IMPLEMENTED but NOT exported / NOT CLI-wired.**
  `quantflow/strategy/sentiment.py` has `SentimentAnalyzer` (ProsusAI/finbert via
  transformers) and `NewsCollector` (RSS). Grep confirms it is referenced **only**
  by itself — absent from every `__init__.__all__` and from the CLI. It is orphaned
  code; not reachable from any user-facing surface.
- **Qlib RD-Agent CLI skeleton — ACTIVE with dependency guard.**
  `quantflow/strategy/rd_agent.py` exposes `quantflow ai rdagent`
  (`quantflow/cli/main.py`). `RDAgentRunner.check_available()` probes for `qlib`
  and fails fast with an install hint (`pip install -e ".[ml]"`) when absent. When
  qlib is present, `discover_factors` runs a baseline Alpha158-style IC evaluation
  (real IC scores, pandas fallback). Full LLM-driven RD-Agent factor search is
  **future work** (blueprint E13-S1).

**Status:** `MLEnsembleStrategy` + RD-Agent CLI = active; `AIFactorEngine` = exported
but unused; FinBERT sentiment = implemented but unexported/unwired.

---

## Consolidated Status Table

| # | Feature area | Status | Primary files |
|---|---|---|---|
| 1 | Strategies (7, dual-mode, YAML) | ACTIVE | `strategy/base.py`, `strategy/catalog.py`, `strategy/templates/*`, `config/strategies/*.yaml` |
| 2 | CLI (9 commands) | ACTIVE | `cli/main.py` |
| 3 | Research Pipeline | ACTIVE | `strategy/research/{backtest,optimizer,report}.py` |
| 4 | Anti-Overfitting Validation | ACTIVE | `strategy/validation/{cpcv,dsr,pbo,wfo,gate,barriers,lookahead,monte_carlo}.py` |
| 5 | Execution | ACTIVE | `execution/{gateway_base,engine,order_router,order_manager,kill_switch,okx_gateway,paper_gateway}.py` |
| 6 | Risk Controls | ACTIVE | `signal/{risk_engine,position_sizer,risk_metrics}.py`, `strategy/engine.py` |
| 7 | Data Layer | ACTIVE | `data/{fetcher,store,feature_store,redis_cache,mtf_aligner,cleaner}.py` |
| 8 | QuantFlow Station Web UI | ACTIVE | `web/{app,security,service,session_manager}.py` |
| 9 | Indicators (27 factors + regime) | ACTIVE | `indicators/{engine,regime}.py`, `indicators/*.py` |
| 10 | AI Layer | MIXED | `strategy/{ai_factors,ml_ensemble,sentiment,rd_agent}.py` |

**Discrepancies from the brief (flagged):**
- The brief's "ScalingPositionSizer → PositionRequest" maps to `PositionSizer.size()`
  emitting a notional that `TradingSession` wraps in a `PositionRequest` — there is
  no `ScalingPositionSizer` class in the code.
- Station exposes 21 API routes (+ index + static) = the documented "23" includes
  the SPA index and static asset routes; 9 functional groups confirmed.
- FinBERT sentiment is implemented but genuinely unexported/unwired (not reachable
  from CLI/API), consistent with the brief.
