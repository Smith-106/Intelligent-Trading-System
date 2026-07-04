# F-001 — ZigZag转折点检测 + 浪型识别引擎

> Role: system-architect | Related decisions: D1, D3

## Architecture

### Module Layout

The ZigZag pivot detector and wave classification engine reside in **L2 (indicators layer)** within `quantflow/indicators/elliott_wave.py`, expanding the existing skeleton. The wave recognition engine is a new component `WaveClassifier` that wraps ZigZag output and applies three iron rules.

```
quantflow/indicators/elliott_wave.py    # L2 — ZigZag + WaveClassifier + Fibonacci
quantflow/indicators/engine.py          # L2 — FactorRegistry integration (register zigzag/wave factors)
```

### Component Responsibilities

1. **ZigZagDetector** (refactored from `zigzag()`): Stateless function accepting `(high, low, threshold)` returning `pd.DataFrame` of pivots. Multi-parameter ZigZag cross-validation (see Q1) runs as a separate function `zigzag_consensus()` that calls `zigzag()` with 2-3 thresholds and merges overlapping pivots.

2. **WaveClassifier**: Accepts pivot DataFrame, applies three iron rules sequentially, returns `WaveCount` dataclass. Implements the enumeration state machine per D3.

3. **FactorRegistry integration**: Register `zigzag_pivots` and `wave_count` as named factors so `IndicatorEngine.compute_all()` can include them.

### Data Flow

```
OHLCV DataFrame
  → zigzag(high, low, threshold) → pivots DataFrame
  → zigzag_consensus(high, low, [0.03, 0.05, 0.08]) → consensus_pivots
  → WaveClassifier.classify(pivots, fib_tolerance) → WaveCount
```

## Interface Contract

### ZigZagDetector

```python
def zigzag(high: pd.Series, low: pd.Series, threshold: float = 0.05) -> pd.DataFrame
# Returns: columns [pivot_idx, pivot_price, pivot_type, pivot_time]

def zigzag_consensus(
    high: pd.Series, low: pd.Series,
    thresholds: list[float] = [0.03, 0.05, 0.08],
    min_overlap: int = 2,
) -> pd.DataFrame
# Returns: consensus pivots where >= min_overlap thresholds agree
```

### WaveClassifier

```python
class WaveClassifier:
    def __init__(self, fib_tolerance: float = 0.15) -> None: ...
    def classify(self, pivots: pd.DataFrame) -> WaveCount: ...
    def classify_progressive(self, pivots: pd.DataFrame) -> WaveCount: ...
```

### Data Model

```python
@dataclass
class Pivot:
    idx: int
    price: float
    pivot_type: Literal[1, -1]  # 1=swing_high, -1=swing_low
    timestamp: int

@dataclass
class WaveCount:
    pivots: list[Pivot]
    labels: list[WaveLabel]
    wave_type: WaveType | None
    is_bullish: bool
    confidence: float  # 0.0-1.0 based on rule adherence
    iron_rule_violations: list[str]
```

The existing `classify_impulse()` and `classify_corrective()` functions MUST be refactored into `WaveClassifier.classify()`, preserving the existing public API (`elliott_wave()` function) for backward compatibility.

## Constraints (RFC 2119)

- C-001: ZigZag detector MUST treat the `threshold` parameter as the minimum price move ratio; pivots below threshold MUST NOT be emitted.
- C-002: `zigzag_consensus()` MUST require at least `min_overlap` parameter agreements before accepting a pivot as consensus.
- C-003: WaveClassifier MUST validate all three iron rules: (1) Wave 2 MUST NOT retrace more than 100% of Wave 1, (2) Wave 3 MUST NOT be the shortest among waves 1/3/5 (relaxed in real-time per Q3), (3) Wave 4 MUST NOT overlap Wave 1 price territory.
- C-004: The "Wave 3 not shortest" rule MUST NOT be enforced during real-time classification while Wave 3 is still forming; it MUST only be applied retrospectively.
- C-005: `WaveCount.confidence` MUST be computed as the fraction of iron rules satisfied, weighted by Fibonacci ratio adherence.
- C-006: The existing `elliott_wave()` top-level function MUST remain backward-compatible; internal refactoring MUST NOT change its input/output signature.

## Test Approach

- **Unit**: Test `zigzag()` on synthetic sinusoidal data with known pivot positions; verify exact pivot indices. Test `zigzag_consensus()` with conflicting thresholds; verify overlap logic. Test `WaveClassifier` with known impulse/corrective wave patterns; verify label assignment.
- **Property-based**: Generate random OHLCV series; verify that iron rule violations are correctly detected and reported in `WaveCount.iron_rule_violations`.
- **Integration**: Feed real BTC/USDT data through the pipeline; compare pivot counts against manual annotation on 20-bar samples.

## TODOs

- Define the exact consensus merge algorithm for `zigzag_consensus()` (within-bar tolerance vs. exact-idx match).
- Determine whether `Pivot.timestamp` uses exchange timestamp or local arrival time (relevant for 24/7 markets per Q4).
- Specify confidence weighting formula for `WaveCount.confidence`.
- Assess whether `classify_impulse()` tolerance parameter needs dynamic adjustment based on volatility regime.
