# System Architect Analysis — 柳玉东波浪理论交易系统

> Contract: guidance-specification.md §system-architect (decisions D1, D3, D4, D5)
> Owns: Six-layer architecture integration, data flow design, interface contracts, wave state machine, layer boundary enforcement, data model, configuration model
> Does not own: Wave theory rule quantification (subject-matter-expert), test strategy and backtest validation (test-strategist)

## 1. Role Mandate (<= 200 words)

The system architect decides how the Elliott Wave trading system integrates into QuantFlow's six-layer architecture (L1-L6), owns the interface contracts between layers, and defines the wave state machine that governs wave classification lifecycle. Per D1, the integration reuses existing infrastructure (StrategyBase, FactorBase, EventBus, PositionSizer, DataFetcher) rather than building standalone components. Per D3, the wave type representation uses an enumeration state machine with deterministic transitions. The architect defers wave theory rule quantification (three iron rules, Fibonacci ratios, alternation rule) to the subject-matter-expert, and test strategy (backtest validation, parameter sensitivity) to the test-strategist. The architect resolves conflicts on layer boundary violations and data flow direction.

## 2. Decision Digest

### Decisions

| ID | Feature | Stance | Constraints (RFC 2119) |
|----|---------|--------|------------------------|
| SA-01 | F-001 | ZigZag detector remains a stateless function in L2; multi-parameter consensus adds robustness per Q1 | C-001: threshold MUST be minimum move ratio; C-002: consensus MUST require min_overlap |
| SA-02 | F-001 | WaveClassifier implements enumeration state machine per D3 with progressive and retrospective modes | C-003: MUST validate three iron rules; C-004: W3-shortest rule MUST NOT apply in real-time |
| SA-03 | F-002 | FibonacciCalculator wraps existing compute_fibonacci_levels with directional and cluster support | C-007: MUST compute directionally; C-010: cluster tolerance MUST be configurable |
| SA-04 | F-002 | CriticalLevelCalculator produces hard/soft invalidation levels consumed by L4 | C-008: MUST emit >=1 hard level per impulse; C-009: hard levels MUST trigger invalidation |
| SA-05 | F-003 | WaveChannelBuilder and DivergenceDetector extend L2 indicator layer | C-012: MUST return None for <3 pivots; C-014: MUST require >=2 pivots for divergence |
| SA-06 | F-004 | ElliottWaveStrategy inherits StrategyBase with 5 wave-segment rules and stateful WaveState | C-017: MUST implement all lifecycle methods; C-021: vectorized and event-driven MUST be consistent |
| SA-07 | F-005 | InvalidationEngine in L4 monitors critical levels; hard stops are risk-layer owned | C-023: MUST check on every price update; C-024: hard stops MUST NOT be overridden by strategy |
| SA-08 | F-006 | WavePositionSizer extends existing PositionSizer per D5 with three-tier scaling model | C-028: MUST NOT exceed max_total_pct; C-031: MUST delegate final validation to PositionSizer |
| SA-09 | F-007 | MTFAligner in L1 reuses DataFetcher per D4 with UTC-based alignment | C-033: MUST use UTC timestamps; C-034: higher TF counts MUST NOT update before bar close |
| SA-10 | F-008 | CLI elliott-wave command group follows existing Typer pattern; config fully YAML-driven | C-039: MUST NOT hardcode parameters; C-040: MUST reuse existing backtest infrastructure |

### Interfaces

| Name | Contract | Consumers |
|------|----------|-----------|
| zigzag() | (high: pd.Series, low: pd.Series, threshold: float) -> pd.DataFrame | WaveClassifier, DivergenceDetector |
| zigzag_consensus() | (high, low, thresholds, min_overlap) -> pd.DataFrame | WaveClassifier |
| WaveClassifier.classify() | (pivots: pd.DataFrame) -> WaveCount | ElliottWaveStrategy, MTFAligner |
| WaveClassifier.classify_progressive() | (pivots: pd.DataFrame) -> WaveCount | ElliottWaveStrategy (live mode) |
| FibonacciCalculator.retracement() | (wave_start, wave_end) -> FibLevels | ElliottWaveStrategy |
| FibonacciCalculator.extension() | (wave_start, wave_end, direction) -> FibTargets | ElliottWaveStrategy |
| CriticalLevelCalculator.invalidate_levels() | (wave_count: WaveCount) -> list[CriticalLevel] | InvalidationEngine, WaveSignalGenerator |
| WaveChannelBuilder.build() | (wave_count, df) -> WaveChannel | None | ElliottWaveStrategy |
| DivergenceDetector.detect() | (df, pivots) -> list[DivergenceSignal] | ElliottWaveStrategy |
| WaveSignalGenerator.enrich() | (action: TradeAction, critical_levels) -> Signal | Signal pipeline |
| InvalidationEngine.check() | (symbol, current_price) -> list[InvalidationEvent] | Risk pipeline |
| WavePositionSizer.size() | (action, portfolio, wave_state) -> float | Position pipeline |
| MTFAligner.align() | (dfs: dict[str, pd.DataFrame]) -> MTFDataFrame | ElliottWaveStrategy |
| MTFAligner.propagate_signal() | (signal, higher_tf_wave) -> Signal | Signal pipeline |
| WaveData (bundle) | dataclass: WaveCount + FibLevels + CriticalLevels + WaveChannel + DivergenceSignals | L3 consumes L2 output |

### Cross-Cutting Positions

| Topic | Stance |
|-------|--------|
| Data Model | WaveCount is the central entity; Pivot, CriticalLevel, FibLevel, DivergenceSignal are supporting entities; WaveState tracks runtime strategy state |
| State Machine | Two-tier: WavePhase (coarse) + WaveLabel (fine); progressive mode for live, retrospective for backtest; hard invalidation forces UNCLASSIFIED |
| Error Handling | Wave classification failure yields WaveCount with confidence=0 and iron_rule_violations populated; never raises exceptions for ambiguous data |
| Observability | 5+ metrics: wave_classification_count, invalidation_events_total, wave_confidence_histogram, mtf_alignment_score, scaling_tier_distribution |
| Configuration | All parameters in elliott_wave.yaml under params/risk/scaling/mtf sections; validated by Pydantic ElliottWaveConfig |
| Boundary Scenarios | Concurrent MTF updates MUST serialize on symbol; hard invalidation MUST be atomic (check + exit); strategy restart MUST rebuild WaveState from pivot history |

### Findings Summary

| Slug | Title | Impact |
|------|-------|--------|
| wave-state-machine | Wave State Machine Design — two-tier phase/label model with progressive and retrospective modes | HIGH — affects F-001, F-004, F-005, F-007 |
| layer-boundary | Layer Boundary Enforcement — WaveData bundle prevents L4 from calling L2 directly | HIGH — affects all features |

## 3. Cross-Cutting Foundations

### Data Model

Five core entities with fields, types, constraints, and relationships:

1. **WaveCount** (central entity)
   - pivots: list[Pivot] — detected swing points
   - labels: list[WaveLabel] — W1-W5 or WA-WC assignments
   - wave_type: WaveType | None — IMPULSE or CORRECTIVE
   - is_bullish: bool — direction of the wave pattern
   - confidence: float — 0.0-1.0, fraction of iron rules satisfied
   - iron_rule_violations: list[str] — which rules failed
   - Relationships: contains Pivots, consumed by FibLevels/CriticalLevels/WaveChannel

2. **Pivot**
   - idx: int — bar index in source DataFrame
   - price: float — price at pivot
   - pivot_type: Literal[1, -1] — swing high or swing low
   - timestamp: int — UTC millisecond timestamp
   - Relationships: belongs to WaveCount, consumed by DivergenceDetector

3. **CriticalLevel**
   - price: float — the invalidation price
   - label: str — descriptive label (e.g., "W1_origin")
   - direction: Direction — which direction breach matters
   - severity: str — "hard" or "soft"
   - wave_label: WaveLabel — which wave this level pertains to
   - Relationships: derived from WaveCount, consumed by InvalidationEngine

4. **FibLevel**
   - ratio: float — Fibonacci ratio (e.g., 0.618)
   - price: float — computed price level
   - label: str — human-readable label
   - Relationships: belongs to FibLevels, aggregated into FibClusters

5. **WaveState** (runtime entity, not persisted)
   - current_count: WaveCount | None — active wave interpretation
   - active_rule: int | None — which trading rule (1-5) is active
   - entry_price: float — current entry price
   - stop_loss: float — current stop loss
   - take_profit: float — current take profit
   - invalidation_level: float — current hard invalidation price
   - last_update_bar: int — bar index of last update
   - Relationships: owned by ElliottWaveStrategy, read by WavePositionSizer

### State Machine

Wave classification lifecycle (WavePhase state machine):

```
                    +------------------+
                    |   UNCLASSIFIED   |
                    +--------+---------+
                             |
                    [5 pivots match impulse pattern]
                             |
                    +--------v---------+
          +-------->| IMPULSE_FORMING  |
          |         +--------+---------+
          |                  |
          |    [W2 confirmed, Fib retrace valid]
          |                  |
          |         +--------v---------+
          |         | IMPULSE_W3_ACTIVE|<----+
          |         +--------+---------+     |
          |                  |               |
          |    [W3 extends beyond W1]        |
          |                  |               |
          |         +--------v---------+     |
          |         | IMPULSE_W4_ACTIVE|     |
          |         +--------+---------+     |
          |                  |               |
          |    [W4 retrace valid, no overlap]|
          |                  |               |
          |         +--------v---------+     |
          |         | IMPULSE_W5_ACTIVE|     |
          |         +--------+---------+     |
          |                  |               |
          |    [W5 complete or divergence]   |
          |                  |               |
          |         +--------v---------+     |
          |         | CORRECTIVE_FORMING|    |
          |         +--------+---------+     |
          |                  |               |
          |    [ABC complete]                |
          |                  |               |
          |         +--------v---------+     |
          +---------|   UNCLASSIFIED   |     |
   [hard            +------------------+     |
    invalidation]                            |
          |                                   |
          +-----------------------------------+
```

Transition table:

| From | To | Trigger | Mode |
|------|----|---------|------|
| UNCLASSIFIED | IMPULSE_FORMING | 5 pivots match impulse pattern | Both |
| IMPULSE_FORMING | IMPULSE_W3_ACTIVE | W2 Fib retrace confirmed | Both |
| IMPULSE_W3_ACTIVE | IMPULSE_W4_ACTIVE | W3 extends beyond W1 peak | Both |
| IMPULSE_W4_ACTIVE | IMPULSE_W5_ACTIVE | W4 retrace valid, no W1 overlap | Both |
| IMPULSE_W5_ACTIVE | CORRECTIVE_FORMING | W5 complete or divergence | Both |
| CORRECTIVE_FORMING | UNCLASSIFIED | ABC complete | Both |
| Any state | UNCLASSIFIED | Hard invalidation level breached | Live only |
| IMPULSE_W3_ACTIVE | IMPULSE_W3_ACTIVE | New bar, W3 still forming (progressive) | Live only |

### Error Handling

Classification and recovery of errors:

| Category | Example | Recovery |
|----------|---------|----------|
| Data Insufficient | <5 pivots for impulse classification | Return WaveCount with confidence=0, no labels |
| Iron Rule Violation | W2 retrace >100% of W1 | Record in iron_rule_violations, attempt corrective classification |
| Ambiguous Pattern | Multiple valid wave counts | Return highest-confidence WaveCount; log alternatives |
| Invalidation Breach | Hard stop level breached | Force UNCLASSIFIED state, emit InvalidationEvent, exit position |
| MTF Misalignment | Weekly and 4H counts contradict | Reduce signal strength, log warning, proceed with lower TF |
| Config Error | Invalid YAML parameter | Raise ConfigError with field name and expected range |

Recovery principles: Wave classification failure MUST NOT raise exceptions to the caller; it MUST return a WaveCount with reduced confidence. InvalidationEngine errors MUST be logged and MUST NOT suppress the exit action.

### Observability

Required metrics (minimum 5):

1. wave_classification_total (counter) — number of wave classifications attempted, by wave_type (impulse/corrective/unclassified)
2. wave_invalidation_events_total (counter) — hard/soft invalidation triggers, by severity
3. wave_confidence_histogram (histogram) — distribution of WaveCount.confidence values
4. mtf_alignment_score_gauge (gauge) — current cross-timeframe alignment score per symbol
5. scaling_tier_distribution (gauge) — current position distribution across trial/scale_in/chase tiers

Log events:

- wave.classified — new wave count assigned (INFO level)
- wave.invalidated — hard/soft invalidation triggered (WARNING level)
- wave.count_adjusted — soft level breach causing count re-evaluation (INFO level)
- mtf.misaligned — weekly and lower TF counts disagree (WARNING level)

Health checks:

- wave_classifier_healthy — last classification within N bars (configurable)
- invalidation_engine_active — InvalidationEngine has registered levels for all open positions

### Configuration

Configurable parameters with validation:

| Section | Parameter | Type | Default | Range |
|---------|-----------|------|---------|-------|
| params | zigzag_threshold | float | 0.03 | (0.01, 0.20) |
| params | zigzag_consensus_thresholds | list[float] | [0.03, 0.05, 0.08] | each in (0.01, 0.20) |
| params | zigzag_min_overlap | int | 2 | (1, len(thresholds)) |
| params | fib_tolerance | float | 0.15 | (0.05, 0.30) |
| params | use_divergence | bool | true | — |
| params | divergence_oscillators | list[str] | [rsi_14, macd_histogram, obv] | subset of available |
| params | atr_stop_mult | float | 1.5 | (0.5, 5.0) |
| risk | max_position_pct | float | 0.10 | (0.01, 0.30) |
| risk | stop_loss_atr_mult | float | 1.5 | (0.5, 5.0) |
| risk | take_profit_fib_extensions | list[float] | [1.618, 2.618] | each > 1.0 |
| scaling | trial_pct | float | 0.125 | (0.05, 0.20) |
| scaling | scale_in_pct | float | 0.25 | (0.10, 0.40) |
| scaling | chase_pct | float | 0.125 | (0.05, 0.20) |
| scaling | max_total_pct | float | 0.50 | (0.20, 0.80) |
| mtf | timeframes | list[str] | [1w, 4h, 1h, 15m] | subset of TIMEFRAMES |
| mtf | alignment_mode | str | closed_only | closed_only or rolling |
| mtf | primary_timeframe | str | 4h | must be in timeframes list |

### Boundary Scenarios

- **Concurrency**: MTF data updates for the same symbol from different timeframes MUST serialize on a per-symbol lock. The InvalidationEngine check-and-exit MUST be atomic to prevent race conditions between price update and position exit.
- **Rate Limiting**: ZigZag computation on large datasets (100k+ bars) MUST support chunked processing to avoid memory pressure. The zigzag_consensus function with 3 thresholds triples computation; results SHOULD be cached per symbol/timeframe.
- **Shutdown**: On graceful shutdown, the current WaveState MUST be logged (not persisted) for debugging. On restart, the strategy MUST rebuild WaveState from pivot history rather than relying on stale state.
- **Cleanup**: When a position is fully closed, InvalidationEngine.clear(symbol) MUST be called to remove registered levels. Stale critical levels MUST NOT trigger invalidation events for closed positions.
- **Scalability**: The system MUST support at least 10 symbols with 4 timeframes each (40 concurrent data streams) without degradation. Wave classification per bar MUST complete within 50ms on standard hardware.
- **Disaster Recovery**: If the data pipeline has a gap (missed bars), the WaveClassifier MUST reclassify from the last confirmed pivot rather than from the gap start, preventing cascading misclassification.

## 4. File Index

| File | Type | Feature | Headings |
|------|------|---------|----------|
| [analysis-F-001-zigzag-wave-identifier.md](analysis-F-001-zigzag-wave-identifier.md) | feature | F-001 | Architecture, Interface Contract, Constraints (RFC 2119), Test Approach, TODOs |
| [analysis-F-002-fibonacci-critical-level.md](analysis-F-002-fibonacci-critical-level.md) | feature | F-002 | Architecture, Interface Contract, Constraints (RFC 2119), Test Approach, TODOs |
| [analysis-F-003-wave-channel-divergence.md](analysis-F-003-wave-channel-divergence.md) | feature | F-003 | Architecture, Interface Contract, Constraints (RFC 2119), Test Approach, TODOs |
| [analysis-F-004-elliott-wave-strategy.md](analysis-F-004-elliott-wave-strategy.md) | feature | F-004 | Architecture, Interface Contract, Constraints (RFC 2119), Test Approach, TODOs |
| [analysis-F-005-wave-signal-risk.md](analysis-F-005-wave-signal-risk.md) | feature | F-005 | Architecture, Interface Contract, Constraints (RFC 2119), Test Approach, TODOs |
| [analysis-F-006-scaling-position.md](analysis-F-006-scaling-position.md) | feature | F-006 | Architecture, Interface Contract, Constraints (RFC 2119), Test Approach, TODOs |
| [analysis-F-007-multi-timeframe-align.md](analysis-F-007-multi-timeframe-align.md) | feature | F-007 | Architecture, Interface Contract, Constraints (RFC 2119), Test Approach, TODOs |
| [analysis-F-008-cli-config-backtest.md](analysis-F-008-cli-config-backtest.md) | feature | F-008 | Architecture, Interface Contract, Constraints (RFC 2119), Test Approach, TODOs |
| [findings-wave-state-machine.md](findings-wave-state-machine.md) | finding | — | Description, Affected Features, Recommendation |
| [findings-layer-boundary.md](findings-layer-boundary.md) | finding | — | Description, Affected Features, Recommendation |

## 5. Outstanding TODOs

1. **Consensus merge algorithm**: Define exact pivot matching logic for zigzag_consensus — within-bar tolerance vs. exact-idx match.
2. **Confidence weighting formula**: Specify how WaveCount.confidence combines iron rule adherence with Fibonacci ratio precision.
3. **Signal metadata schema**: Define where hard_stop, soft_stop, and invalidation_level are stored in enriched Signal objects.
4. **InvalidationEngine execution model**: Determine synchronous (in bar handler) vs. asynchronous (separate monitoring loop) execution.
5. **Hard stop vs. drawdown priority**: Specify interaction between InvalidationEngine hard stops and existing RiskEngine._check_drawdown().
6. **Target position source**: Define whether WavePositionSizer target position comes from Kelly-based PositionSizer or fixed config.
7. **MTF alignment score formula**: Define how cross-timeframe wave count consistency is measured.
8. **Rolling vs. closed_only default**: Determine which alignment mode is default for 24/7 crypto markets.
9. **MTF FeatureStore schema**: Specify whether multi-timeframe data uses separate parquet files or a unified schema.
10. **Analyze command output format**: Define whether quantflow elliott-wave analyze outputs text, JSON, or both.
11. **Live mode confirmation**: Determine whether run --mode live requires additional safety prompts.
12. **WaveState persistence**: Decide whether WaveState persists across TradingSession restarts or rebuilds from pivot history.
