# Finding: Layer Boundary Enforcement for Elliott Wave Components

> Role: system-architect | Impact: HIGH

## Description

The eight features span L1 through L6, but the architecture constraint (§5.2) requires strict unidirectional dependencies. The current codebase already has minor violations (e.g., `FeatureStore` imports `IndicatorEngine` directly). The Elliott Wave integration must not introduce new layer violations.

Key boundary decisions:

| Component | Layer | Depends On | Must NOT Depend On |
|-----------|-------|-----------|-------------------|
| ZigZagDetector | L2 | L1 (OHLCV data) | L3, L4, L5 |
| WaveClassifier | L2 | L2 (ZigZag) | L3, L4 |
| FibonacciCalculator | L2 | L2 (WaveCount) | L3, L4 |
| CriticalLevelCalculator | L2 | L2 (WaveCount) | L4 (stop placement) |
| WaveChannelBuilder | L2 | L2 (WaveCount) | L3, L4 |
| DivergenceDetector | L2 | L2 (pivots), L2 (oscillators) | L3, L4 |
| ElliottWaveStrategy | L3 | L2 (all above) | L5 (Gateway) |
| WaveSignalGenerator | L4 | L3 (TradeAction), L2 (CriticalLevel) | L5 |
| InvalidationEngine | L4 | L2 (CriticalLevel), EventBus | L3 (strategy logic) |
| WavePositionSizer | L4 | L4 (PositionSizer), L3 (WaveState) | L5 |
| MTFAligner | L1 | L1 (DataFetcher) | L2, L3, L4 |

A notable concern: `CriticalLevelCalculator` computes invalidation levels that are consumed by L4's `InvalidationEngine`. This is a valid L2→L4 data flow (L2 produces data, L4 consumes it), but L4 MUST NOT call L2 directly for stop-placement decisions — the critical levels flow through the strategy (L3) as part of `WaveCount` metadata.

## Affected Features

- All features (cross-cutting architectural concern)

## Recommendation

Introduce a `WaveData` dataclass that bundles all L2 outputs (WaveCount, FibLevels, CriticalLevels, WaveChannel, DivergenceSignals) into a single object that L3 consumes. L4 components receive only the subset they need through L3's `TradeAction` metadata, never by calling L2 directly. This preserves the unidirectional dependency flow.
