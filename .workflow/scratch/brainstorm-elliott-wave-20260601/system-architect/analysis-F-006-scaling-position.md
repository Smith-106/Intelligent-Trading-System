# F-006 — 分批建仓/出场策略（试仓10-15%/加仓20-30%/追仓10-15%）

> Role: system-architect | Related decisions: D5

## Architecture

### Module Layout

Scaling position management extends the existing `PositionSizer` in `quantflow/signal/position_sizer.py` (L4). Per D5, the approach extends rather than replaces the existing interface.

```
quantflow/signal/position_sizer.py    # L4 — extended with WavePositionSizer
quantflow/signal/wave_sizer.py        # L4 — NEW: wave-specific scaling logic
```

### Scaling Model

The wave-based scaling model defines three position tiers:

| Tier | Wave Context | Allocation | Trigger |
|------|-------------|-----------|---------|
| Trial (试仓) | W2 confirmed → W3 expected | 10-15% of target position | Fib retrace confirmed |
| Scale-in (加仓) | W3 breakout confirmed | 20-30% of target position | W1 peak breakout |
| Chase (追仓) | W4 pullback → W5 expected | 10-15% of target position | Fib retrace to 23.6-38.2% of W3 |

Total maximum: 40-60% of target position (never 100% on a single wave count).

### Exit Scaling

| Tier | Wave Context | Allocation | Trigger |
|------|-------------|-----------|---------|
| Partial exit 1 | W3 Fib extension 1.618 | 30-40% of position | Target reached |
| Partial exit 2 | W5 channel target | 30-40% of position | Channel upper boundary |
| Final exit | Hard stop or divergence | Remaining position | Invalidation or divergence |

### Data Flow

```
TradeAction (from F-004, with rule_id)
  → WavePositionSizer.size(action, portfolio, wave_state) → float (notional)
  → existing PositionSizer validates against max_position_pct
```

## Interface Contract

### WavePositionSizer

```python
class WavePositionSizer:
    def __init__(self, config: WaveScalingConfig) -> None: ...
    def size(self, action: TradeAction, portfolio: Portfolio, wave_state: WaveState) -> float: ...
    def next_tier(self, symbol: str, current_exposure: float) -> ScalingTier | None: ...
    def exit_size(self, symbol: str, exit_reason: str, current_position: float) -> float: ...

@dataclass
class ScalingTier:
    name: str          # "trial", "scale_in", "chase"
    pct: float         # fraction of target position (0.0-1.0)
    wave_rule: int     # 1-5, which rule this tier corresponds to

@dataclass
class WaveScalingConfig:
    trial_pct: float = 0.125      # 12.5% (midpoint of 10-15%)
    scale_in_pct: float = 0.25    # 25% (midpoint of 20-30%)
    chase_pct: float = 0.125      # 12.5% (midpoint of 10-15%)
    max_total_pct: float = 0.50   # 50% max of target position
    exit_tier1_pct: float = 0.35  # 35% partial exit
    exit_tier2_pct: float = 0.35  # 35% partial exit
    # Remaining 30% exits on hard stop
```

## Constraints (RFC 2119)

- C-028: `WavePositionSizer` MUST NOT allow cumulative position to exceed `max_total_pct` of the target position for any single wave count.
- C-029: The trial tier (试仓) MUST be the first entry; `scale_in` and `chase` tiers MUST NOT execute unless a prior tier is already in place.
- C-030: Exit sizing MUST respect the tiered model; partial exits SHOULD be proportional to the position accumulated at each tier.
- C-031: `WavePositionSizer.size()` MUST delegate final validation to the existing `PositionSizer` (max_position_pct clamp), preserving the existing risk guardrail.
- C-032: `WaveScalingConfig` parameters MUST be configurable via `elliott_wave.yaml` under a `scaling` section.

## Test Approach

- **Unit**: Test that cumulative position across three tiers equals `max_total_pct`. Test that `next_tier()` returns `None` when `max_total_pct` is already reached. Test exit sizing for each tier.
- **Integration**: Simulate a full wave cycle with trial → scale_in → chase → partial exits; verify final position is zero after all exits.
- **Edge cases**: Scale-in attempt without prior trial position — MUST be rejected. Hard stop during chase tier — verify full remaining position exits.

## TODOs

- Define how `target position` is determined — whether it comes from `PositionSizer` (Kelly-based) or a fixed notional from config.
- Specify whether partial exits generate separate `Signal` objects or a single signal with a quantity field.
- Determine how `WaveScalingConfig` integrates with the existing `RiskConfig` in `AppConfig`.
