# F-004 — ElliottWaveStrategy（继承StrategyBase）+ 5种浪段交易规则

> Role: subject-matter-expert | Related decisions: D1, D2, D5

## Architecture

ElliottWaveStrategy inherits from `StrategyBase` and implements both `generate_signals()` for backtest mode and `on_bar()` for event-driven mode. It consumes wave labels from F-001, Fibonacci levels from F-002, and channel/divergence signals from F-003.

The strategy encodes five distinct wave-segment trading rules, each with explicit entry conditions, position sizing guidance, and exit criteria. The strategy MUST NOT directly access the execution layer; it emits signals through `StrategyContext.emit_signal()`.

### Five Wave-Segment Trading Rules

**Rule 1: W2-End Entry (Buy the Dip)**
- Entry trigger: Price reaches W2 Fibonacci zone (0.5-0.618 retrace of W1) AND volume contracts AND MACD bullish divergence at W2 trough.
- Direction: LONG (for bullish impulse), SHORT (for bearish impulse).
- Signal strength: 0.8 (high conviction — W2 end is the highest-probability entry in impulse).
- Confirmation: W2 low MUST NOT breach W1 start (Iron Law 1).

**Rule 2: W3-Trend Entry (Breakout Confirmation)**
- Entry trigger: Price breaks above W1 high (for bullish) with expanding volume AND MACD histogram expanding (not just positive).
- Direction: LONG (bullish), SHORT (bearish).
- Signal strength: 1.0 (strongest trend signal — W3 is the longest and most powerful wave).
- Confirmation: Volume at breakout MUST exceed 20-bar average volume.

**Rule 3: W4-End Entry (Buy the Second Dip)**
- Entry trigger: Price reaches W4 Fibonacci zone (0.382-0.5 retrace of W3) AND W2/W4 alternation pattern holds AND volume contracts.
- Direction: LONG (bullish), SHORT (bearish).
- Signal strength: 0.6 (moderate conviction — W4 end is less certain than W2 end).
- Confirmation: W4 low MUST NOT enter W1 price territory (Iron Law 3).

**Rule 4: W5-Peak Exit (Target Reached)**
- Exit trigger: Price reaches W5 Fibonacci target zone (1.618x extension of W1) AND MACD bearish divergence AND volume contraction.
- Direction: Exit LONG (bullish), Exit SHORT (bearish).
- Signal strength: 0.7 for partial exit, 0.9 for full exit with divergence confirmation.
- Confirmation: Channel projection from F-003 overlaps with Fibonacci target.

**Rule 5: B-Wave Exit (Correction Reversal)**
- Exit trigger: Price reaches B-wave Fibonacci zone (0.382-0.618 retrace of A-wave) AND B-wave volume < A-wave volume.
- Direction: Exit LONG (after bullish A-wave), Exit SHORT (after bearish A-wave).
- Signal strength: 0.5 (low conviction — B-waves are the most variable corrective wave).
- Confirmation: B-wave MUST NOT exceed A-wave origin (otherwise wave count is invalid, switch to complex correction).

### Signal Strength Rationale

Signal strengths are calibrated to feed into the PositionSizer (F-006). The mapping:
- 1.0 = Full position allowed (W3 trend entry)
- 0.8 = Large position (W2 end entry)
- 0.7 = Partial exit (W5 target reached)
- 0.6 = Moderate position (W4 end entry)
- 0.5 = Small position / exit (B-wave exit)

### Current Code Assessment

No `ElliottWaveStrategy` class exists yet. The `elliott_wave.yaml` config provides basic parameters but lacks the five-rule structure. The strategy MUST be implemented from scratch, following the `StrategyBase` interface.

## Interface Contract

```python
class ElliottWaveStrategy(StrategyBase):
    def on_init(self, ctx: StrategyContext) -> None:
        """Load wave config, initialize indicator dependencies."""

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        """Event-driven: check wave conditions, emit signals per 5 rules."""

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Vectorized: compute entries/exits from wave labels + Fibonacci."""

    def get_required_indicators(self) -> list[dict[str, Any]]:
        """Declare ZigZag, MACD, volume MA as dependencies."""
```

## Constraints (RFC 2119)

1. ElliottWaveStrategy MUST inherit from `StrategyBase` and implement both `generate_signals()` and `on_bar()`. The `generate_signals()` method MUST produce identical trading decisions as `on_bar()` when applied to the same historical data.
2. Each of the five trading rules MUST be implemented as a distinct method (e.g., `_check_w2_entry()`, `_check_w3_entry()`) to enable independent testing and configuration.
3. The strategy MUST NOT emit signals when the wave count is `tentative`. Only `probable` and `confirmed` wave labels qualify for signal generation. This addresses Q2 (lag in endpoint detection).
4. W3 trend entry (Rule 2) MUST require volume confirmation. Breakout without volume expansion SHOULD be treated as a false breakout with reduced signal strength (0.4 instead of 1.0).
5. W5 exit (Rule 4) MUST use both Fibonacci target AND at least one divergence confirmation (MACD or volume). Target-only exits without divergence SHOULD use a trailing stop instead.
6. B-wave exit (Rule 5) SHOULD have a lower signal strength than W5 exit because B-waves are inherently variable. The strategy MUST NOT treat B-wave exit as a new impulse entry unless a fresh wave count is confirmed.
7. All five rule thresholds MUST be configurable via `elliott_wave.yaml`. Hardcoded defaults are permitted but MUST be overridable.

## Test Approach

- **Unit tests per rule**: For each of the 5 rules, construct a synthetic bar sequence that triggers the rule and verify the correct signal is emitted. Then construct a sequence that should NOT trigger and verify silence.
- **Integration test**: Feed BTC/USDT 4H data with known wave patterns and verify that signals fire at the correct wave positions.
- **Backtest consistency test**: Run both `generate_signals()` and `on_bar()` on the same dataset and verify identical entry/exit timestamps.
- **Regression test**: Verify that the existing trend_following and mean_reversion strategies are not affected.

## TODOs

- Define the exact YAML schema for the five-rule configuration.
- Determine how `generate_signals()` maps wave labels (which are sparse — only at pivots) to a dense entry/exit series.
- Study whether a "no-signal zone" is needed between wave entries (e.g., prevent W3 entry if W2 entry signal is still active).
- Design the interaction between rule priorities when multiple rules could fire simultaneously (e.g., W4 end entry coinciding with W5 partial exit from a higher-degree wave).
