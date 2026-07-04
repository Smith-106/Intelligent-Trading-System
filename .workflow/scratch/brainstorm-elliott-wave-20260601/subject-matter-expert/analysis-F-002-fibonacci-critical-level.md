# F-002 — 斐波那契回撤/扩展计算器 + 多空临界位标注

> Role: subject-matter-expert | Related decisions: D2, Q5

## Architecture

The Fibonacci calculator operates as a stateless computation module within L2 (indicators), consuming wave pivot points from F-001 and producing a structured set of retracement and extension levels. The Critical Level annotator consumes these levels alongside wave context to identify and track multi-strategy critical price points.

### Component Design

1. **FibonacciLevelCalculator** — Pure function that computes all standard retracement (0.236, 0.382, 0.5, 0.618, 0.786) and extension (1.0, 1.272, 1.618, 2.618, 4.236) levels from any wave segment. Each level MUST carry metadata: ratio, price, type (retrace/extend), and which wave it belongs to.

2. **CriticalLevelAnnotator** — Stateful component that maintains a set of active critical levels. A CriticalLevel is defined as a Fibonacci-derived price that, if breached, invalidates the current wave count. This directly addresses Q5 (dynamic critical levels).

### Critical Level Types per Wave Segment

| Wave Context | Critical Level | Invalidation If Breached |
|---|---|---|
| W2 retracement zone | W1 start price | Iron Law 1 violation |
| W3 extension | W1 end price (0.618 retrace of W1) | W3 fails to extend |
| W4 retracement zone | W1 end price | Iron Law 3 violation |
| W5 target | 1.618x extension of W1 | W5 fails to reach target |
| B-wave retracement | A-wave start | B exceeds A origin (complex correction) |

### Current Code Assessment

The existing `compute_fibonacci_levels()` is a minimal implementation:
- It computes levels from a single wave segment (start, end).
- It does NOT annotate which levels are critical vs. informational.
- It does NOT track dynamic updates as wave counts change.
- The formula `wave_end - amplitude * ratio` is applied identically for both up and down waves, which is incorrect: for a down wave, retracement levels should be computed as `wave_end + |amplitude| * ratio`.

## Interface Contract

```python
@dataclass
class FibLevel:
    ratio: float
    price: float
    level_type: str  # "retracement" | "extension"
    wave_id: str     # e.g., "W1", "W3"
    is_critical: bool

@dataclass
class CriticalLevel:
    price: float
    label: str           # e.g., "W1-High", "W2-0.618-Retrace"
    wave_context: str    # e.g., "bullish-impulse"
    invalidates: str     # what wave count becomes invalid
    direction: str       # "above" | "below"

def compute_fib_levels_annotated(
    wave_start: float,
    wave_end: float,
    wave_id: str,
    critical_ratios: list[float] | None = None,
) -> list[FibLevel]:
    """Compute Fibonacci levels with critical annotations."""

def identify_critical_levels(
    wave_labels: pd.DataFrame,
    current_price: float,
) -> list[CriticalLevel]:
    """Identify active critical levels from current wave count."""
```

## Constraints (RFC 2119)

1. The Fibonacci calculator MUST compute levels correctly for both up-waves and down-waves. For up-waves, retracement levels descend from wave_end. For down-waves, retracement levels ascend from wave_end.
2. Critical levels MUST be recomputed whenever the wave count is updated. Stale critical levels from an invalidated count MUST be removed from the active set.
3. Each critical level MUST carry an `invalidates` field describing exactly which wave interpretation becomes invalid if the level is breached. This information MUST be propagated to the signal generator (F-005).
4. The standard Fibonacci ratios MUST include: 0.236, 0.382, 0.5, 0.618, 0.786 (retracement) and 1.0, 1.272, 1.618, 2.618, 4.236 (extension).
5. Wave-specific critical ratios SHOULD be configurable via `elliott_wave.yaml`. The defaults per wave segment are: W2 retrace zone [0.5, 0.618], W3 extension [1.618], W4 retrace zone [0.382, 0.5], W5 target [1.618, 2.618].
6. The critical level annotator MUST emit an event when a critical level is breached, enabling the signal generator (F-005) to trigger wave invalidation logic.
7. Price precision for Fibonacci levels MUST be maintained to at least 2 decimal places for BTC/USDT (0.01 USDT). Rounding MUST NOT introduce errors larger than the instrument tick size.

## Test Approach

- **Unit tests**: Verify Fibonacci level computation for known wave segments with hand-calculated expected values. Test both up-wave and down-wave directions.
- **Round-trip tests**: Compute levels from a wave, then verify that the wave start/end prices appear in the retracement levels at ratio 0.0 and 1.0.
- **Critical level lifecycle tests**: Create a wave count, compute critical levels, update the wave count, verify that stale levels are removed and new levels are added.
- **Precision tests**: Verify that BTC prices at the ~90,000 level produce Fibonacci levels with errors < 0.01 USDT.

## TODOs

- Fix the directional bug in the existing `compute_fibonacci_levels()` (same formula used for up and down waves).
- Define the event schema for critical level breach notifications.
- Study how many critical levels typically coexist for a single instrument and whether prioritization is needed.
- Determine whether critical levels from lower timeframes should influence higher timeframe wave counts.
