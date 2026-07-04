# F-004 — ElliottWaveStrategy（继承StrategyBase）+ 5种浪段交易规则

> Role: system-architect | Related decisions: D1, D3

## Architecture

### Module Layout

The strategy extends the existing `quantflow/strategy/templates/elliott_wave.py` (L3). The current skeleton provides basic W2/W4 entry and W5/WC exit logic; the full implementation adds 5 distinct wave-segment trading rules with stateful wave tracking.

```
quantflow/strategy/templates/elliott_wave.py  # L3 — ElliottWaveStrategy (enhanced)
quantflow/strategy/base.py                    # L3 — StrategyBase + StrategyContext
quantflow/indicators/elliott_wave.py          # L2 — WaveClassifier, FibCalculator (consumed)
```

### Five Wave-Segment Trading Rules

| Rule | Wave Context | Entry Condition | Exit Condition |
|------|-------------|----------------|----------------|
| R1 | W2 completion → W3 | Fib retrace 38.2-61.8% confirmed | Fib extension 1.618 of W1 |
| R2 | W3 in progress | Breakout above W1 peak (bullish) | Trailing stop at 50% of W3 amplitude |
| R3 | W4 completion → W5 | Fib retrace 23.6-38.2% of W3 confirmed | Wave channel upper boundary |
| R4 | W5 completion | Divergence confirmed (exit only) | Fib extension 1.0 of W1 or channel target |
| R5 | C wave completion | C = 1.618*A Fib target reached | Prior impulse origin (full retrace) |

### Stateful Strategy Design

The strategy MUST maintain a `WaveState` object that tracks the current wave interpretation and updates progressively as new bars arrive. This addresses Q2 (lagging W2/W4 confirmation) by using probabilistic labeling that hardens over time.

### Data Flow

```
Bar event → StrategyContext.on_bar()
  → WaveClassifier.classify_progressive(pivots) → WaveCount (updated)
  → RuleEngine.evaluate(wave_count, current_position) → list[TradeAction]
  → ctx.emit_signal(direction, strength, price)
```

## Interface Contract

### ElliottWaveStrategy (enhanced)

```python
class ElliottWaveStrategy(StrategyBase):
    def __init__(self, params: dict | None = None) -> None: ...
    def on_init(self, ctx: StrategyContext) -> None: ...
    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None: ...
    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]: ...
    def get_required_indicators(self) -> list[dict[str, Any]]: ...
```

### WaveState

```python
class WaveState:
    current_count: WaveCount | None
    active_rule: int | None        # 1-5, which rule is currently active
    entry_price: float
    stop_loss: float
    take_profit: float
    invalidation_level: float
    last_update_bar: int
```

### TradeAction

```python
@dataclass
class TradeAction:
    action: Literal["enter", "exit", "adjust_stop", "adjust_tp"]
    direction: Direction
    strength: float
    price: float
    rule_id: int  # 1-5
    reason: str
```

## Constraints (RFC 2119)

- C-017: `ElliottWaveStrategy` MUST inherit from `StrategyBase` and implement all three lifecycle methods: `on_init()`, `on_bar()`, `generate_signals()`.
- C-018: The strategy MUST NOT call any Gateway method directly; all order intent flows through `ctx.emit_signal()` (architecture constraint §5.5).
- C-019: `WaveState` MUST be reset to initial state when a hard invalidation level is breached (see F-005).
- C-020: Signal strength MUST correlate with `WaveCount.confidence` — higher confidence wave counts MUST produce stronger signals.
- C-021: `generate_signals()` (vectorized mode) MUST produce identical entry/exit decisions to `on_bar()` (event-driven mode) given the same data, ensuring backtest-live consistency.
- C-022: The strategy MUST register its required indicators via `get_required_indicators()`, returning at minimum `["zigzag_pivots", "wave_count", "rsi_14", "atr_14"]`.

## Test Approach

- **Unit**: Test each of the 5 rules independently with synthetic wave data. Verify that `WaveState` transitions correctly when new pivots are confirmed. Test that hard invalidation resets `WaveState`.
- **Integration**: Run the strategy through `TradingSession` in backtest mode with BTC/USDT 4H data. Compare vectorized vs. event-driven signal parity.
- **Regression**: Existing test suite for `ElliottWaveStrategy.generate_signals()` MUST continue to pass.

## TODOs

- Define the exact mapping from `WaveCount.confidence` to signal strength (linear, threshold-based, or sigmoid).
- Specify how `WaveState` persists across TradingSession restarts (if at all).
- Determine whether Rule R2 (W3 trailing stop) interacts with the L4 risk engine's drawdown limits.
