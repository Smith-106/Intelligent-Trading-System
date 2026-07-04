# Finding: Wave State Machine Design

> Role: system-architect | Impact: HIGH

## Description

The core challenge in Elliott Wave automation is the "thousand people, thousand counts" problem (千人千浪). The enumeration state machine (per D3) must represent wave progression as a deterministic state machine with clear transitions, while also supporting probabilistic labeling during real-time classification (per Q2).

The wave state machine has two operational modes:

1. **Retrospective mode** (backtest): Full data is available. The classifier runs on complete pivot sequences, applying all three iron rules strictly. State transitions are deterministic.

2. **Progressive mode** (live/paper): Data arrives bar-by-bar. The classifier assigns provisional labels that may be revised as new pivots form. The "Wave 3 not shortest" rule is deferred (per Q3).

```
State Machine (Simplified):

  UNCLASSIFIED → IMPULSE_W2_CONFIRMED → IMPULSE_W3_FORMING → IMPULSE_W3_CONFIRMED
                     ↓                       ↓                       ↓
               (hard invalidation)    (soft adjustment)      IMPULSE_W4_FORMING
                                                               ↓
                                                         IMPULSE_W4_CONFIRMED
                                                               ↓
                                                         IMPULSE_W5_FORMING
                                                               ↓
                                                         IMPULSE_COMPLETE → CORRECTIVE_ABC

  Any state --[hard invalidation]--> UNCLASSIFIED
```

## Affected Features

- F-001 (WaveClassifier state machine implementation)
- F-004 (ElliottWaveStrategy WaveState tracking)
- F-005 (InvalidationEngine triggers state resets)
- F-007 (MTF alignment requires state machines per timeframe)

## Recommendation

Adopt a two-tier state machine: `WavePhase` enum for coarse-grained state (UNCLASSIFIED, IMPULSE_FORMING, CORRECTIVE_FORMING, COMPLETE) and `WaveLabel` for fine-grained position within a phase. The `WaveClassifier` owns the state machine; the strategy reads but does not mutate it. Hard invalidation events from `InvalidationEngine` force a transition to UNCLASSIFIED regardless of current state.
