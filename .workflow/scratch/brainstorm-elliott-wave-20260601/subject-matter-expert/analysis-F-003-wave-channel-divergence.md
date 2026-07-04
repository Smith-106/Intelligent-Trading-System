# F-003 — 波浪通道线 + 成交量/MACD背离验证

> Role: subject-matter-expert | Related decisions: D2, Q2

## Architecture

This feature combines two independent but complementary verification mechanisms for wave endpoints. Both operate within L2 (indicators) and produce signals consumed by the wave strategy (F-004) and signal generator (F-005).

### Component Design

1. **WaveChannelCalculator** — Draws the baseline from W1 peak to W3 peak, then constructs a parallel line through the W2 trough. The channel upper boundary projects the W5 target. This is the standard Elliott Wave channeling technique.

2. **DivergenceDetector** — Identifies three types of divergence at wave endpoints:
   - **Price-MACD divergence**: Price makes new extreme but MACD histogram does not (W5 exhaustion, B-wave weakness).
   - **Price-Volume divergence**: Price extends but volume contracts (W5 exhaustion, W3 confirmation via volume expansion).
   - **Price-RSI divergence**: Already partially implemented in `wave_momentum_divergence()`, but currently only checks RSI at adjacent pivots, not at the wave-degree level.

### Channel Construction Rules

For a bullish impulse (W1 low -> W1 high -> W2 low -> W3 high -> W4 low -> W5 high):

- **Baseline**: Line from W1 high to W3 high
- **Channel lower**: Parallel to baseline, passing through W2 low
- **Channel upper**: Parallel to baseline, passing through W3 high (upper band)
- **W5 target zone**: Where the channel upper band intersects the projected time of W5

For a bearish impulse, invert all directions.

### Divergence Detection Rules

| Divergence Type | Signal | Wave Context | Confirmation Requirements |
|---|---|---|---|
| MACD lower high at W5 peak | W5 exhaustion / sell | Bullish impulse W5 | Price > W3 high AND MACD histogram < W3 peak MACD |
| Volume contraction at W5 | W5 exhaustion / sell | Bullish impulse W5 | Price > W3 high AND volume < W3 volume |
| MACD higher low at W2/W4 trough | W2/W4 end / buy | Retracement zone | Price < prior pivot AND MACD histogram > prior trough MACD |
| Volume contraction at W2/W4 | W2/W4 end / buy | Retracement zone | Price at retrace level AND volume declining over 3+ bars |

### Current Code Assessment

The existing `wave_momentum_divergence()` function:
- Only uses RSI, not MACD or volume.
- Compares adjacent pivots (i-2 vs i) which may not correspond to the correct wave-degree pivots.
- Does not distinguish between wave-degree divergence (W3 vs W5) and sub-wave divergence.
- Returns raw divergence signals without wave context.

## Interface Contract

```python
@dataclass
class WaveChannel:
    baseline_start: tuple[int, float]   # (bar_index, price)
    baseline_end: tuple[int, float]
    upper_band: list[tuple[int, float]]
    lower_band: list[tuple[int, float]]
    w5_target_zone: tuple[float, float]  # (lower, upper) price range

def compute_wave_channel(
    wave_pivots: pd.DataFrame,
    bars_ahead: int = 20,
) -> Optional[WaveChannel]:
    """Construct Elliott Wave channel from impulse wave pivots."""

@dataclass
class DivergenceSignal:
    bar_index: int
    divergence_type: str   # "macd_bearish", "macd_bullish", "volume_bearish", "volume_bullish"
    wave_context: str      # "W5-peak", "W2-trough", "W4-trough"
    strength: float        # 0.0-1.0

def detect_divergence(
    close: pd.Series,
    macd_hist: pd.Series,
    volume: pd.Series,
    wave_pivots: pd.DataFrame,
) -> pd.Series:
    """Detect multi-type divergence at wave endpoints."""
```

## Constraints (RFC 2119)

1. The wave channel MUST be constructed from the W1-W3 baseline. The W5 target MUST be projected within the channel boundaries. A W5 that exits the channel SHOULD be flagged as an extended wave (possible diagonal or truncation scenario).
2. MACD divergence at W5 MUST compare the MACD histogram value at the W5 peak against the W3 peak, not against the W1 peak. The comparison MUST use the histogram, not the MACD line or signal line.
3. Volume divergence MUST compare volume at W5 against volume at W3. Volume contraction at W5 (volume < 0.7 * W3 volume) SHOULD be treated as a secondary confirmation signal, not a primary signal.
4. Divergence detection MUST NOT trigger on sub-wave degree. Only wave-degree pivots (those identified by F-001 as W1-W5 or WA-WC) qualify for divergence checks.
5. The divergence detector SHOULD support configurable lookback windows for volume averaging (default: 3 bars for short-term, 20 bars for trend).
6. Wave channel projections MUST be bounded. Projections extending beyond 2x the W1-W3 duration SHOULD be truncated and flagged as low-confidence.
7. Both the channel calculator and divergence detector MUST operate on the same pivot set produced by F-001 to ensure consistency.

## Test Approach

- **Unit tests**: Verify channel construction with synthetic pivots at known coordinates. Check that parallel lines are mathematically correct (same slope).
- **Divergence accuracy tests**: Construct OHLCV sequences with known divergence patterns and verify detection.
- **False positive tests**: Feed trending data without divergence and verify that the detector does not trigger.
- **Channel truncation tests**: Verify that long-duration projections are bounded.
- **Integration tests**: Run channel + divergence on historical BTC/USDT data and verify that W5 targets align with actual price action.

## TODOs

- Determine the optimal MACD parameters for crypto markets (standard 12/26/9 vs. adapted for 24/7 trading).
- Study whether volume profile (not just raw volume) provides better divergence signals for crypto.
- Define how to handle diagonal triangles where W5 may not reach the channel target.
- Investigate whether the existing RSI divergence in `wave_momentum_divergence()` should be refactored or replaced.
