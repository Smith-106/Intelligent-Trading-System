# TC-003 — StrategyLayer

| Field | Value |
|-------|-------|
| **ID** | TC-003 |
| **Type** | L3-strategy |
| **Features** | FT-001 (Strategies), FT-003 (Research Pipeline), FT-004 (Anti-Overfitting Validation), FT-010 (AI Layer) |

## Code Locations

- `quantflow/strategy/base.py:70` — `StrategyBase(ABC)` (`on_init`, `on_bar`, `on_tick`, `generate_signals` abstract), `StrategyContext` (L16, `emit_signal`/`flush_signals`)
- `quantflow/strategy/engine.py:46` — **`TradingSession`** (unified backtest/paper/live engine; orchestrator crossing L4/L5/L6)
- `quantflow/strategy/catalog.py:85` — `get_strategy_definitions()` (7 strategies + factory + param_space + config_path); `load_strategy_config` (L209, deep-copy to avoid `@cache` mutation)
- `quantflow/strategy/ai_factors.py:20` — `AIFactorEngine` (Meta-Labeling, expanding CV splits; exported via `strategy/__init__`, consumed by `MLEnsembleStrategy`)
- `quantflow/strategy/rd_agent.py` — `RDAgentRunner` (Qlib RD-Agent factor mining skeleton; dependency guard for optional qlib `[ml]` extra; Alpha158-style baseline IC evaluation; CLI-wired via `ai rdagent`), `DiscoveredFactor`, `RDAgentConfig`, `QlibNotAvailableError`
- `quantflow/strategy/sentiment.py` — `SentimentAnalyzer` (FinBERT/ProsusAI, lazy transformers/torch + graceful degradation), `NewsCollector` (CryptoPanic/CoinDesk RSS). **Implemented + tested but NOT exported from `__init__` / NOT CLI-wired**
- `quantflow/strategy/elliott_wave_strategy.py:21` — `LiuYudongWaveStrategy`
- `quantflow/strategy/research/` — `backtest.py` (`BacktestEngine`, renamed from `VectorBTEngine`), `optimizer.py` (`StrategyOptimizer`), `report.py`, `elliott_wave_backtest.py`
- `quantflow/strategy/templates/` — 7 concrete strategies + `_runtime.py` (rolling helpers)
- `quantflow/strategy/validation/` — `cpcv.py` (CPCV), `dsr.py` (DSR), `pbo.py` (PBO, ISS-029/030 finite-mask), `wfo.py` (WFO), `gate.py:26` (`validation_gate` GO/NO-GO unified pipeline), `lookahead.py` (static look-ahead leak detector), `monte_carlo.py` (path-level stress), `barriers.py` (triple-barrier labeling), `signal_quality.py`, `_common.py` (shared finite-normalize helper)

## Exported Symbols

`AIFactorEngine`, `BacktestEngine`, `BacktestResult`, `DiscoveredFactor`, `ElliottWaveStrategy`, `FundingRateStrategy`, `LiuYudongWaveStrategy`, `LookaheadFinding`, `LookaheadReport`, `MLEnsembleStrategy`, `MeanReversionStrategy`, `MetaLabelResult`, `MomentumRotationStrategy`, `MonteCarloResult`, `NewsCollector`, `QlibNotAvailableError`, `RDAgentConfig`, `RDAgentRunner`, `SentimentAnalyzer`, `StrategyBase`, `StrategyContext`, `StrategyDefinition`, `StrategyOptimizer`, `TradingSession`, `TrendFollowingStrategy`, `VolatilityBreakoutStrategy`, `WFOFoldResult`, `WFOResult`, `WalkForwardOptimization`, `WaveContext`, `aggregate_signal_quality`, `closes`, `cpcv_backtest`, `deflated_sharpe_ratio`, `ewm_next`, `ewm_series`, `generate_report`, `generate_synthetic_wave_data`, `get_strategy_definition`, `get_strategy_definitions`, `get_strategy_factories`, `get_strategy_specs`, `highs`, `list_strategy_summaries`, `load_strategy_config`, `lows`, `minimum_track_record_length`, `monte_carlo_stress`, `probability_of_overfitting`, `profit_target_exit`, `profit_target_exit_series`, `returns_bootstrap_stress`, `rolling_average_true_ranges`, `rolling_mean_at`, `rolling_mean_optional_at`, `rolling_std_at`, `run_backtest`, `sanitize_metric_array`, `scan_strategies`, `scan_strategy`, `signal_quality_metrics`, `simple_rsi_last`, `split_cpcv`, `summarize_strategy`, `trade_shuffle_stress`, `triple_barrier_labels`, `true_range_value`, `true_ranges`, `validation_gate`, `volumes`, `walk_forward_optimization`

## Dependencies

- **Imports**: `common`, `indicators`, intra-`strategy`; `engine.py` also imports `execution`, `signal`, `monitoring` (intended orchestrator boundary, not a violation).
- **Imported by**: `cli/`, `web/` (service, session_manager).

## Notes

- **Dual-mode API**: every strategy implements vectorized `generate_signals(df)` (research) + incremental `on_bar(ctx, bar)` (live/paper) per arch spec. Parity required.
- `BacktestEngine` replaces VectorBT (Py3.14+ numba incompat). New code referencing `VectorBTEngine` raises ImportError.
- AI layer: `MLEnsembleStrategy` + `AIFactorEngine` (Meta-Labeling) + `SentimentAnalyzer`/`NewsCollector` (FinBERT) **implemented+tested**. Qlib RD-Agent: CLI skeleton wired (`ai rdagent` → `RDAgentRunner`) with dependency guard (qlib optional `[ml]` extra; absent→install hint, present→Alpha158-style baseline IC eval). Full RD-Agent LLM factor search is a future layer on top.
- Duplicate `_positive_class_probability` / split helpers in `ml_ensemble.py:18-69` + `ai_factors.py:20-28` — dedup candidate.
- **ISS-022 signal consolidation (fixed)**: `signal/generator.py:consolidate_signals` `avg_strength` is now a weighted mean (`weighted_strength / total_weight`, L86) instead of the prior `total_weight / n_signals` arithmetic mean — multi-strategy consolidated signals no longer over-count weak contributors.
- **ISS-029/030 validation NaN handling (fixed)**: `validation/pbo.py` uses a NaN sentinel for failed paths (L79) + finite-mask (`np.isfinite`, L100) to exclude them from PBO, rather than coercing to `0.0` (which forced `is_positive=False` and silently biased PBO upward). No finite paths → fail-closed `pbo=1.0` (forces NO-GO) instead of `0.0`. `_common.py` provides the shared finite-normalize helper.

*Auto-generated by codebase-refresh at 2026-07-25T00:00:00Z*
