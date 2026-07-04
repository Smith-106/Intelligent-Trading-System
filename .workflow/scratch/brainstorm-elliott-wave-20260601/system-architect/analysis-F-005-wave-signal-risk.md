# F-005 — 波浪信号生成器 + 数浪失效规则 + 硬/软止损

> Role: system-architect | Related decisions: D1, D5

## Architecture

### Module Layout

Wave-specific signal generation and invalidation rules extend L4 (signal/risk layer). The existing `SignalGenerator` and `RiskEngine` are extended with wave-aware logic rather than replaced.

```
quantflow/signal/generator.py        # L4 — extended with wave signal enrichment
quantflow/signal/risk_engine.py      # L4 — extended with invalidation stop checks
quantflow/signal/wave_signal.py      # L4 — NEW: WaveSignalGenerator + InvalidationEngine
```

### Component Responsibilities

1. **WaveSignalGenerator**: Translates `TradeAction` from the strategy layer into enriched `Signal` objects with wave-specific metadata (wave label, rule ID, invalidation level). This sits between the strategy and the generic `SignalGenerator`.

2. **InvalidationEngine**: Monitors price against `CriticalLevel` objects. When a hard invalidation level is breached, it emits a `WaveInvalidation` event and forces position exit. When a soft level is breached, it triggers count re-evaluation.

### Hard vs. Soft Stop Classification

| Stop Type | Trigger | Action |
|-----------|---------|--------|
| Hard stop | Wave 1 origin breached (W2 > 100% retrace) | Immediate exit, reset WaveState |
| Hard stop | Wave 3 origin breached (W4 > W3 start) | Immediate exit, reset WaveState |
| Soft stop | Wave 4 retrace exceeds 38.2% of W3 | Adjust count, recalculate targets |
| Soft stop | Fib cluster level breached | Reduce position, widen stop |

### Data Flow

```
TradeAction (from F-004)
  → WaveSignalGenerator.enrich(action, critical_levels) → Signal (enriched)
  → RiskEngine.check(signal, portfolio) → RiskDecision
  → InvalidationEngine.monitor(price, critical_levels) → WaveInvalidation event (if triggered)
  → EventBus.publish(EVENT_RISK, invalidation) → Strategy receives reset
```

## Interface Contract

### WaveSignalGenerator

```python
class WaveSignalGenerator:
    def enrich(self, action: TradeAction, critical_levels: list[CriticalLevel]) -> Signal: ...
    def attach_stops(self, signal: Signal, hard_stop: float, soft_stop: float) -> Signal: ...
```

### InvalidationEngine

```python
class InvalidationEngine:
    def __init__(self, event_bus: EventBus) -> None: ...
    def register_levels(self, symbol: str, levels: list[CriticalLevel]) -> None: ...
    def check(self, symbol: str, current_price: float) -> list[InvalidationEvent]: ...
    def clear(self, symbol: str) -> None: ...

@dataclass
class InvalidationEvent:
    symbol: str
    level: CriticalLevel
    current_price: float
    action_required: Literal["exit_immediate", "adjust_count", "reduce_position"]
```

### EventBus Extension

A new event type `EVENT_WAVE_INVALIDATION = "wave_invalidation"` MUST be added to `quantflow/common/models.py` alongside existing event constants.

## Constraints (RFC 2119)

- C-023: `InvalidationEngine` MUST check all registered hard invalidation levels on every price update; a breach MUST trigger immediate position exit.
- C-024: Hard stop breaches MUST NOT be overridden by the strategy — the risk layer owns hard stop execution.
- C-025: Soft stop breaches SHOULD trigger count re-evaluation rather than immediate exit; the strategy MAY choose to adjust or hold.
- C-026: `WaveSignalGenerator.attach_stops()` MUST embed hard and soft stop prices as signal metadata so the execution layer can place stop-loss orders.
- C-027: `InvalidationEngine` MUST clear registered levels when `clear(symbol)` is called, preventing stale invalidation checks after position closure.

## Test Approach

- **Unit**: Test `InvalidationEngine.check()` with a known set of critical levels and prices that sequentially breach hard and soft levels. Verify correct `action_required` values.
- **Integration**: Simulate a full wave cycle where Wave 2 invalidation is triggered mid-trade; verify that `EVENT_WAVE_INVALIDATION` is published and the strategy receives the reset signal.
- **Edge cases**: Price gaps through a hard stop level (crypto flash crash); verify that the invalidation still fires on the next check even if the exact level was never traded at.

## TODOs

- Define the exact metadata schema for enriched `Signal` objects (where to store hard_stop, soft_stop, invalidation_level).
- Specify whether `InvalidationEngine` runs synchronously in the bar handler or asynchronously via a separate monitoring loop.
- Determine the interaction between InvalidationEngine hard stops and the existing `RiskEngine._check_drawdown()` — which takes priority.
