# F-005 — 波浪信号生成器 + 数浪失效规则 + 硬/软止损

> Role: subject-matter-expert | Related decisions: D2, Q5

## Architecture

The wave signal generator extends the existing `SignalGenerator` with wave-specific logic. It operates in L4 (signal/risk layer) and consumes raw signals from ElliottWaveStrategy (F-004), enriching them with wave invalidation context and stop-loss levels.

Three sub-components:

1. **WaveSignalGenerator** — Wraps the base `SignalGenerator` and adds wave metadata (active wave label, critical levels, invalidation price) to each signal.

2. **WaveInvalidationEngine** — Monitors price against critical levels from F-002. When a critical level is breached, the engine emits an invalidation event and forces signal reversal or closure.

3. **WaveStopLossManager** — Computes hard and soft stop-loss levels based on wave context. Hard stops are based on iron law boundaries (non-negotiable). Soft stops are based on Fibonacci levels and channel boundaries (adjustable).

### Wave Invalidation Rules

| Scenario | Invalidation Trigger | Action |
|---|---|---|
| Iron Law 1 breach | Price moves beyond W1 start | Close position, invalidate current count, reclassify |
| Iron Law 2 breach | W3 confirmed shorter than both W1 and W5 | Close position, reclassify as complex correction |
| Iron Law 3 breach | W4 enters W1 price zone | Close position, invalidate impulse, reclassify as diagonal or correction |
| Critical Fibonacci breach | Price exceeds B-wave origin | Switch from simple ABC to complex correction |
| Channel breakout | Price exits channel in unexpected direction | Reduce position, reassess wave degree |

### Hard vs. Soft Stop-Loss

| Type | Level Source | Adjustability | When Used |
|---|---|---|---|
| Hard stop | Iron Law boundary (W1 start, W1 end) | MUST NOT be moved against position | All wave entries |
| Soft stop | Fibonacci retrace level (0.618, 0.786) | MAY be tightened as wave progresses | W2/W4 entry |
| Trailing stop | Wave channel boundary | Moves with channel projection | W3 trend following |
| Time stop | N bars after expected wave endpoint | Fixed | All entries when wave stalls |

### Current Code Assessment

The existing `SignalGenerator` is a simple direction/strength aggregator. It lacks:
- Wave context attachment to signals.
- Invalidation monitoring.
- Stop-loss level computation.
- Integration with the `RiskEngine`.

The existing `RiskEngine` (in `signal/risk_engine.py`) handles generic risk checks but has no wave-specific logic. The wave invalidation engine MUST integrate with it, not replace it.

## Interface Contract

```python
@dataclass
class WaveSignal:
    base_signal: Signal
    wave_label: str          # e.g., "W3"
    wave_context: str        # e.g., "bullish-impulse"
    hard_stop: float         # iron law boundary price
    soft_stop: float         # fibonacci-based price
    invalidation_levels: list[CriticalLevel]
    time_stop_bar: int       # bar index after which time stop triggers

class WaveSignalGenerator:
    def enrich_signal(
        self, signal: Signal, wave_state: WaveState,
    ) -> WaveSignal:
        """Add wave context and stop levels to a raw strategy signal."""

class WaveInvalidationEngine:
    def check_invalidation(
        self, current_price: float, wave_state: WaveState,
    ) -> Optional[InvalidationEvent]:
        """Check if current price invalidates the active wave count."""

    def reclassify(
        self, wave_state: WaveState, invalidation: InvalidationEvent,
    ) -> WaveState:
        """Attempt to reclassify after invalidation."""
```

## Constraints (RFC 2119)

1. Hard stop-loss levels MUST be set at iron law boundaries and MUST NOT be moved away from the position direction. For a LONG entry at W2 end, the hard stop is W1 start price. No override is permitted.
2. Soft stop-loss levels SHOULD be set at the next Fibonacci retrace level beyond the entry. For a W2 entry at 0.618 retrace, the soft stop is at 0.786 retrace.
3. The invalidation engine MUST check all active critical levels on every bar. A breach of any critical level MUST trigger an invalidation event within 1 bar of the breach.
4. When a wave count is invalidated, the engine MUST attempt reclassification before closing positions. If reclassification produces a valid alternative count, positions MAY be adjusted rather than closed.
5. If reclassification fails (no valid wave count exists), the engine MUST close all positions associated with the invalidated count and MUST emit a "wave-uncertain" signal with strength 0.0.
6. Time stops SHOULD activate when a wave has not reached its expected endpoint within 1.5x the duration of the prior wave. Time stops MUST NOT close positions; they SHOULD reduce signal strength to trigger the risk engine position reduction logic.
7. The wave signal generator MUST attach wave context to every signal. Signals without wave context MUST be rejected by the execution layer for this strategy.
8. Trailing stops during W3 trend following MUST follow the wave channel lower band (for LONG) or upper band (for SHORT). The trailing step MUST NOT exceed the channel width.

## Test Approach

- **Unit tests for invalidation**: Construct wave states with known critical levels, simulate price crossing those levels, verify that invalidation events fire correctly.
- **Reclassification tests**: After invalidation, verify that the engine attempts alternative wave counts and produces valid alternatives when possible.
- **Stop-loss precision tests**: Verify that hard stops are set exactly at iron law boundary prices, with no rounding drift.
- **Time stop tests**: Simulate a wave that stalls (no new pivot for extended duration) and verify time stop activation.
- **Integration tests**: Run the full signal pipeline (F-004 -> F-005 -> RiskEngine) on historical data and verify that invalidation events lead to correct position management.

## TODOs

- Define the `WaveState` data structure that tracks the active wave count, critical levels, and position associations.
- Determine the reclassification protocol: which alternative wave counts are attempted first (diagonal? complex correction? degree shift?).
- Study whether the existing `RiskEngine` can be extended or whether a dedicated `WaveRiskEngine` subclass is needed.
- Define the event schema for invalidation events so the execution layer can react appropriately.
- Investigate interaction with Kill Switch (L5) when multiple positions are invalidated simultaneously.
