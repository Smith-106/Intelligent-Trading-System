# TC-003 — StrategyLayer

| Field | Value |
|-------|-------|
| **ID** | TC-003 |
| **Type** | L3-strategy |
| **Features** | FT-001 (Strategies), FT-003 (Research Pipeline), FT-004 (Anti-Overfitting Validation), FT-010 (AI Layer) |
| **Last Updated** | 2026-08-05T05:37:59Z |

## Code Locations

- `quantflow/strategy/base.py`
- `quantflow/strategy/engine.py`
- `quantflow/strategy/catalog.py`
- `quantflow/strategy/ai_factors.py`
- `quantflow/strategy/sentiment.py`
- `quantflow/strategy/elliott_wave_strategy.py`
- `quantflow/strategy/rd_agent.py`
- `quantflow/strategy/factory.py`
- `quantflow/strategy/__init__.py`
- `quantflow/strategy/research/__init__.py`
- `quantflow/strategy/research/backtest.py`
- `quantflow/strategy/research/elliott_wave_backtest.py`
- `quantflow/strategy/research/optimizer.py`
- `quantflow/strategy/research/report.py`
- `quantflow/strategy/templates/__init__.py`
- `quantflow/strategy/templates/_runtime.py`
- `quantflow/strategy/templates/elliott_wave.py`
- `quantflow/strategy/templates/funding_rate.py`
- `quantflow/strategy/templates/mean_reversion.py`
- `quantflow/strategy/templates/ml_ensemble.py`
- `quantflow/strategy/templates/momentum_rotation.py`
- `quantflow/strategy/templates/trend_following.py`
- `quantflow/strategy/templates/volatility_breakout.py`
- `quantflow/strategy/validation/__init__.py`
- `quantflow/strategy/validation/_common.py`
- `quantflow/strategy/validation/barriers.py`
- `quantflow/strategy/validation/cpcv.py`
- `quantflow/strategy/validation/dsr.py`
- `quantflow/strategy/validation/gate.py`
- `quantflow/strategy/validation/lookahead.py`
- `quantflow/strategy/validation/monte_carlo.py`
- `quantflow/strategy/validation/pbo.py`
- `quantflow/strategy/validation/recursive.py`
- `quantflow/strategy/validation/signal_quality.py`
- `quantflow/strategy/validation/wfo.py`

## Exported Symbols

- `AIFactorEngine`
- `BacktestEngine`
- `BacktestResult`
- `DiscoveredFactor`
- `EVENT_FUNDING` — Funding-rate data event (v0.4.0 Wave 1)
- `EVENT_OI` — Open-interest data event (v0.4.0 Wave 1)
- `ElliottWaveStrategy`
- `FundingRateStrategy`
- `LiuYudongWaveStrategy`
- `LookaheadFinding`
- `LookaheadReport`
- `MLEnsembleStrategy`
- `MeanReversionStrategy`
- `MetaLabelResult`
- `MomentumRotationStrategy`
- `MonteCarloResult`
- `NewsCollector`
- `QlibNotAvailableError`
- `RDAgentCliUnavailableError` — Raised when RD-Agent CLI is unavailable
- `RDAgentConfig`
- `RDAgentRunner`
- `RecursiveReport`
- `SentimentAnalyzer`
- `StrategyBase`
- `StrategyContext`
- `StrategyDefinition`
- `StrategyOptimizer`
- `TradingSession`
- `TrendFollowingStrategy`
- `VolatilityBreakoutStrategy`
- `WFOFoldResult`
- `WFOResult`
- `WalkForwardOptimization`
- `WaveContext`
- `aggregate_signal_quality`
- `closes`
- `cpcv_backtest`
- `create_all_per_symbol`
- `create_per_symbol`
- `deflated_sharpe_ratio`
- `ewm_next`
- `ewm_series`
- `generate_report`
- `generate_synthetic_wave_data`
- `get_strategy_definition`
- `get_strategy_definitions`
- `get_strategy_factories`
- `get_strategy_specs`
- `highs`
- `list_strategy_summaries`
- `load_strategy_config`
- `lows`
- `minimum_track_record_length`
- `monte_carlo_stress`
- `probability_of_overfitting` — PBO probability-of-overfitting computation
- `profit_target_exit`
- `profit_target_exit_series`
- `returns_bootstrap_stress`
- `rolling_average_true_ranges`
- `rolling_mean_at`
- `rolling_mean_optional_at`
- `rolling_std_at`
- `run_backtest`
- `sanitize_metric_array`
- `scan_recursive`
- `scan_strategies`
- `scan_strategy`
- `signal_quality_metrics`
- `simple_rsi_last`
- `split_cpcv`
- `summarize_strategy`
- `trade_shuffle_stress`
- `triple_barrier_labels`
- `true_range_value`
- `true_ranges`
- `validation_gate`
- `volumes`
- `walk_forward_optimization`

## Dependencies

- Upstream: `quantflow/common` (models, exceptions, config).
- Downstream consumers: see feature maps for consumer wiring.

---

*Refreshed by codebase-refresh at 2026-08-05T05:39:39Z*
