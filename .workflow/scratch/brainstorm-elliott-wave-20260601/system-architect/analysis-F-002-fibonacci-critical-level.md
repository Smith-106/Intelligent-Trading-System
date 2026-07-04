# F-002 — 斐波那契回撤/扩展计算器 + 多空临界位标注

> Role: system-architect | Related decisions: D1, D3

## Architecture

### Module Layout

The Fibonacci calculator extends `quantflow/indicators/elliott_wave.py` (L2), building on the `compute_fibonacci_levels()` function already present. A new `CriticalLevelCalculator` identifies price levels where wave counts invalidate.

```
quantflow/indicators/elliott_wave.py    # L2 — FibonacciCalculator + CriticalLevelCalculator
```

### Component Responsibilities

1. **FibonacciCalculator**: Extends `compute_fibonacci_levels()` to support directional computation (up-wave vs. down-wave), cluster-level aggregation (multiple wave degrees), and extension target computation for entry/exit zones.

2. **CriticalLevelCalculator**: Given a `WaveCount`, computes the price levels where the current wave interpretation becomes invalid. For example, Wave 2 retracing beyond 100% of Wave 1 invalidates the impulse count.

### Data Flow

```
WaveCount (from F-001)
  → FibonacciCalculator.retracement(wave_start, wave_end) → FibLevels
  → FibonacciCalculator.extension(wave_start, wave_end, direction) → FibTargets
  → CriticalLevelCalculator.invalidate_levels(wave_count) → list[CriticalLevel]
```

## Interface Contract

### FibonacciCalculator

```python
class FibonacciCalculator:
    RATIOS_RETRACE: ClassVar[list[float]] = [0.236, 0.382, 0.5, 0.618, 0.786]
    RATIOS_EXTEND: ClassVar[list[float]] = [1.0, 1.272, 1.618, 2.618, 4.236]

    def retracement(self, wave_start: float, wave_end: float) -> FibLevels: ...
    def extension(self, wave_start: float, wave_end: float, direction: Direction) -> FibTargets: ...
    def cluster_levels(self, wave_counts: list[WaveCount]) -> FibClusters: ...
```

### CriticalLevelCalculator

```python
class CriticalLevelCalculator:
    def invalidate_levels(self, wave_count: WaveCount) -> list[CriticalLevel]: ...

@dataclass
class CriticalLevel:
    price: float
    label: str            # e.g. "W1_start", "W1_end", "W3_161.8%"
    direction: Direction  # LONG if break above matters, SHORT if break below
    severity: str         # "hard" (count invalid) | "soft" (adjust count)
    wave_label: WaveLabel # which wave this level pertains to
```

### Data Models

```python
@dataclass
class FibLevel:
    ratio: float
    price: float
    label: str  # e.g. "0.618"

@dataclass
class FibLevels:
    wave_start: float
    wave_end: float
    levels: list[FibLevel]

@dataclass
class FibTarget:
    ratio: float
    price: float
    usage: str  # "tp" (take-profit) | "entry_zone"

@dataclass
class FibTargets:
    targets: list[FibTarget]

@dataclass
class FibCluster:
    price: float
    contributing_ratios: list[str]
    density: int  # number of Fib levels near this price

@dataclass
class FibClusters:
    clusters: list[FibCluster]
```

## Constraints (RFC 2119)

- C-007: `FibonacciCalculator.retracement()` MUST compute levels as `wave_end - amplitude * ratio` for up-waves and `wave_end + amplitude * ratio` for down-waves, ensuring directional correctness.
- C-008: `CriticalLevelCalculator` MUST emit at minimum one hard-invalidation level per impulse wave (Wave 1 origin for bullish, Wave 1 peak for bearish).
- C-009: Critical levels with severity "hard" MUST trigger `WaveInvalidation` when price breaches them; severity "soft" MUST trigger count adjustment only.
- C-010: `FibonacciCalculator.cluster_levels()` MUST aggregate Fib levels across wave degrees within a configurable price tolerance (default: 0.5% of current price).
- C-011: The existing `compute_fibonacci_levels()` function MUST remain backward-compatible; the new `FibonacciCalculator` class wraps and extends it.

## Test Approach

- **Unit**: Verify retracement levels against hand-computed values for known wave structures. Test extension targets with directional variants. Verify critical level computation for a complete 5-wave impulse.
- **Edge cases**: Zero-amplitude waves (wave_start == wave_end) MUST return empty levels. Negative amplitude (down-wave) MUST produce levels in the correct direction.
- **Integration**: Feed WaveCount from F-001 into CriticalLevelCalculator; verify that hard invalidation levels match iron rule boundaries.

## TODOs

- Define the exact price tolerance for Fib clustering (0.5% default needs validation against crypto volatility).
- Determine whether `CriticalLevel.severity` maps directly to stop-loss placement or requires an intermediate translation layer in L4.
- Specify how dynamic critical level updates (Q5) propagate — event-driven or polling.
