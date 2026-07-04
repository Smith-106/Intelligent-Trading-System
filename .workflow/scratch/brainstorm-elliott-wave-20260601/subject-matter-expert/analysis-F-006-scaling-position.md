# F-006 — 分批建仓/出场策略（试仓10-15%/加仓20-30%/追仓10-15%）

> Role: subject-matter-expert | Related decisions: D5

## Architecture

The scaling position module extends the existing `PositionSizer` with wave-specific scaling logic. It operates within L4 (signal/risk layer) and translates wave entry rules into a progressive position-building plan.

### Scaling Model

The scaling model divides position building into three phases, each triggered by a specific wave condition and sized according to conviction level:

| Phase | Trigger | Position Size (% of portfolio) | Cumulative | Stop Level |
|---|---|---|---|---|
| Trial (试仓) | W2 end entry signal | 10-15% | 10-15% | Hard stop at W1 start |
| Scale-in (加仓) | W3 breakout confirmation | 20-30% | 30-45% | Soft stop at W2 low |
| Chase (追仓) | W3 continuation + volume | 10-15% | 40-60% | Trailing stop (channel) |

For exits, a symmetric scaling-out model applies:

| Phase | Trigger | Exit Size (% of position) | Remaining |
|---|---|---|---|
| Partial exit 1 | W5 Fibonacci target reached | 50% | 50% |
| Partial exit 2 | MACD divergence at W5 | 30% | 20% |
| Final exit | B-wave signal or trailing stop | 20% | 0% |

### Position Sizing Interaction with Signal Strength

The five wave rules (F-004) emit signals with different strengths. The scaling model MUST map these strengths to scaling phases:

| Rule | Signal Strength | Scaling Phase |
|---|---|---|
| W2 end entry | 0.8 | Trial (10-15%) |
| W3 breakout | 1.0 | Scale-in (20-30%) |
| W4 end entry | 0.6 | Trial (10-15%) — new position or add to existing |
| W5 exit | 0.7-0.9 | Scaling out (50% -> 80% -> 100%) |
| B-wave exit | 0.5 | Full exit if remaining position is small |

### Current Code Assessment

The existing `PositionSizer` uses a half-Kelly method that produces a single position size per signal. It does not support:
- Multi-phase position building.
- Scaling in based on progressive confirmation.
- Scaling out with partial exits.
- Wave-context-aware sizing.

Per D5, the approach is to extend `PositionSizer` rather than create an independent module. The extension MUST be backward-compatible: existing strategies that do not provide wave context MUST continue to use the half-Kelly method.

## Interface Contract

```python
@dataclass
class ScalingPlan:
    phases: list[ScalingPhase]
    total_target_pct: float      # max cumulative position as % of portfolio
    hard_stop: float
    soft_stop: float

@dataclass
class ScalingPhase:
    name: str                    # "trial", "scale_in", "chase"
    trigger_rule: str            # wave rule that activates this phase
    target_pct: float            # position % for this phase
    stop_level: float
    is_active: bool = False
    is_filled: bool = False

class WavePositionSizer(PositionSizer):
    def plan_scaling(
        self, signal: Signal, wave_context: WaveContext,
    ) -> ScalingPlan:
        """Compute a multi-phase scaling plan for a wave signal."""

    def next_phase_size(
        self, plan: ScalingPlan, current_position: float, portfolio: Portfolio,
    ) -> float:
        """Return the order size for the next unfilled phase."""

    def check_phase_trigger(
        self, plan: ScalingPlan, current_bar: Bar, wave_state: WaveState,
    ) -> Optional[str]:
        """Check if a new scaling phase should be activated."""
```

## Constraints (RFC 2119)

1. The total cumulative position across all scaling phases MUST NOT exceed the `max_position_pct` configured in `elliott_wave.yaml`. The default MUST be 60% of portfolio.
2. Each scaling phase MUST have its own stop-loss level. The trial phase stop MUST be the hard stop (iron law boundary). The scale-in stop SHOULD be the W2 low (or equivalent). The chase stop SHOULD be the wave channel boundary.
3. If a hard stop is hit during any phase, ALL phases MUST be closed simultaneously. Partial position retention after a hard stop violation is prohibited.
4. The trial phase MUST be filled before the scale-in phase can activate. A gap in confirmation (e.g., W3 breakout without a prior W2 entry) SHOULD still allow a single-phase entry at the scale-in size, but MUST NOT trigger the trial phase retroactively.
5. Scaling out MUST follow the reverse order: the chase portion exits first, then scale-in, then trial. This ensures the lowest-conviction position is exited first.
6. The `WavePositionSizer` MUST be backward-compatible with `PositionSizer`. When no `WaveContext` is provided, it MUST fall back to the parent class half-Kelly sizing.
7. Position percentages in the scaling plan SHOULD be configurable via `elliott_wave.yaml`. Hardcoded defaults are: trial 12%, scale-in 25%, chase 12% (total 49%, leaving margin below 60% cap).
8. The scaling plan MUST be recalculated when the wave count is invalidated (per F-005). Invalidation during the trial phase triggers full exit. Invalidation during later phases triggers proportional exit based on the reclassification result.

## Test Approach

- **Unit tests per phase**: Verify that each scaling phase produces the correct order size given portfolio value and signal strength.
- **Cumulative cap tests**: Verify that the total position never exceeds `max_position_pct` even when all phases are active.
- **Stop cascade tests**: Simulate a hard stop hit during the chase phase and verify that all phases close.
- **Backward compatibility tests**: Call `WavePositionSizer.size()` without wave context and verify it produces the same result as the parent `PositionSizer`.
- **Exit scaling tests**: Simulate W5 target + divergence and verify the 50%/30%/20% exit sequence.
- **Integration test**: Run a full trade lifecycle (W2 entry -> W3 scale-in -> W3 chase -> W5 partial exit -> B-wave full exit) on historical data.

## TODOs

- Define the `WaveContext` data structure that the `WavePositionSizer` requires.
- Determine how partial fills in one phase affect the sizing of subsequent phases.
- Study whether the 60% max position cap is appropriate for BTC (high volatility) or should be adaptive.
- Design the interaction with the existing `RiskEngine` — the risk engine drawdown circuit breaker MUST be able to halt scaling mid-plan.
- Investigate whether position scaling should account for correlation when trading multiple symbols simultaneously.
