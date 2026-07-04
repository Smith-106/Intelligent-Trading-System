# F-001 — ZigZag转折点检测 + 浪型识别引擎（三大铁律验证）

> Role: subject-matter-expert | Related decisions: D2, D3, Q1, Q2

## Architecture

The ZigZag pivot detector serves as the foundation of the entire wave identification pipeline. It MUST operate as a pure function within L2 (indicators layer), producing a `pd.DataFrame` of pivots consumed by the wave classification engine.

Two sub-components form the identification engine:

1. **Multi-Parameter ZigZag** — Runs ZigZag detection at 3-5 threshold values (e.g., 3%, 5%, 8%, 12%) and computes consensus pivots. A pivot appears in the consensus set when it is identified by at least N-1 of N parameter sets within a configurable bar tolerance window. This directly addresses Q1 (parameter sensitivity).

2. **Wave Classification Engine** — Consumes consensus pivots and applies the three iron laws as hard boolean predicates, then applies Fibonacci ratio checks as soft validation with configurable tolerance. The engine MUST use an enumerative state machine (D3) where each state corresponds to a wave label (W1..W5, WA..WC) and transitions are governed by the iron laws.

### Current Code Assessment

The existing `elliott_wave.py` implements a single-threshold ZigZag and a `classify_impulse()` function that partially encodes the iron laws. Critical gaps:

- **Iron Law 2 (Wave 3 cannot be shortest) is NOT enforced.** The current code only checks `r3 < 0.618 - tolerance` which is a Fibonacci ratio check, not the iron law that W3 MUST NOT be shorter than both W1 and W5.
- **Iron Law 1 (Wave 2 cannot retrace below W1 start) is weakly checked.** The current code uses Fibonacci ratio bounds but does not explicitly verify that the W2 low does not breach the W1 origin price.
- **Iron Law 3 (Wave 4 cannot enter Wave 1 price zone) is checked** but the overlap logic is inverted for the bullish case: `prices[4] >= prices[1]` checks W4-low vs W1-high, which is correct. However, the variable naming (`prices[4]` = W5 endpoint in a 5-pivot array) makes this confusing and error-prone.

## Interface Contract

```python
def zigzag_multi(
    high: pd.Series,
    low: pd.Series,
    thresholds: list[float] = [0.03, 0.05, 0.08],
    consensus_ratio: float = 0.6,
    bar_tolerance: int = 3,
) -> pd.DataFrame:
    """Multi-parameter ZigZag with consensus pivot extraction."""

def classify_impulse_strict(
    pivots: pd.DataFrame,
    fib_tolerance: float = 0.15,
) -> Optional[pd.DataFrame]:
    """Classify impulse with ALL THREE iron laws enforced as hard constraints."""

def classify_corrective_extended(
    pivots: pd.DataFrame,
    fib_tolerance: float = 0.20,
) -> Optional[pd.DataFrame]:
    """Classify ABC with extended patterns (zigzag, flat, triangle hints)."""
```

## Constraints (RFC 2119)

1. The three iron laws MUST be enforced as hard boolean predicates in `classify_impulse_strict()`. No tolerance override is permitted for iron law violations.
2. Iron Law 1: `wave2_end_price` MUST NOT be beyond `wave1_start_price` in the direction of Wave 1. For bullish impulse: W2 low >= W1 start low. For bearish: W2 high <= W1 start high.
3. Iron Law 2: `wave3_length` MUST be greater than at least one of {wave1_length, wave5_length}. Equivalently, Wave 3 MUST NOT be the shortest among Waves 1, 3, and 5.
4. Iron Law 3: `wave4_end_price` MUST NOT re-enter the price territory of Wave 1. For bullish: W4 low > W1 end high. For bearish: W4 high < W1 end low.
5. The multi-parameter ZigZag consensus mechanism MUST use at least 3 threshold values. The default consensus_ratio SHOULD be 0.6 (2 of 3 thresholds agree).
6. Fibonacci ratio checks SHOULD be applied as soft validation after iron laws pass. A wave pattern that passes all three iron laws but fails Fibonacci ratios SHOULD still be accepted with a reduced confidence score.
7. The wave classification engine MUST NOT modify historical wave labels on confirmation of new data. Instead, it MUST emit a new label set with a version identifier, preserving the prior interpretation for audit.
8. Real-time wave labeling MUST use probabilistic annotation (Q2). A pivot at the right edge of data MUST carry a `confirmation_status` field: `tentative`, `probable`, or `confirmed`.

## Test Approach

- **Unit tests**: Verify each iron law in isolation with synthetic pivot sequences. For each law, test both pass and fail cases with exact price values.
- **Integration tests**: Feed historical BTC/USDT 4H data through the full pipeline and verify that classified waves satisfy all three iron laws.
- **Sensitivity tests**: Vary ZigZag threshold from 1% to 15% and measure pivot consistency rate. Target: consensus pivots MUST have > 80% overlap across the threshold range for BTC data.
- **Regression tests**: Ensure the existing `zigzag()` function behavior is preserved as a special case (single-threshold mode).

## TODOs

- Formalize the probabilistic confirmation model for Q2 (tentative/probable/confirmed thresholds).
- Define the exact bar tolerance window for consensus pivot merging.
- Investigate whether Wave 3 "not shortest" should be relaxed during real-time (Q3) and what the reclassification protocol is when it fails retroactively.
- Study the interaction between multi-threshold ZigZag and the existing `elliott_wave()` function to plan the refactor path.
