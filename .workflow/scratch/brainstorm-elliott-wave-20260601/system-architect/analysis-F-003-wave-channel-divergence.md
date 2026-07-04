# F-003 — 波浪通道线 + 成交量/MACD背离验证

> Role: system-architect | Related decisions: D1, D3

## Architecture

### Module Layout

Wave channel construction and divergence detection extend `quantflow/indicators/elliott_wave.py` (L2). The divergence detector builds on the existing `wave_momentum_divergence()` but adds volume divergence and MACD histogram divergence.

```
quantflow/indicators/elliott_wave.py    # L2 — WaveChannelBuilder + DivergenceDetector
quantflow/indicators/momentum.py        # L2 — existing RSI (dependency)
quantflow/indicators/trend.py           # L2 — existing MACD (dependency)
quantflow/indicators/volume.py          # L2 — existing OBV (dependency)
```

### Component Responsibilities

1. **WaveChannelBuilder**: Given a `WaveCount` with at least 3 impulse pivots, constructs parallel channel lines. The base channel connects Wave 1 and Wave 3 peaks (bullish) or troughs (bearish); the parallel line projects the Wave 5 target.

2. **DivergenceDetector**: Extends `wave_momentum_divergence()` to support multiple oscillator sources (RSI, MACD histogram, OBV rate-of-change). Detects bearish divergence at Wave 5 peaks and bullish divergence at corrective wave lows.

### Data Flow

```
WaveCount (from F-001)
  + OHLCV DataFrame (with computed RSI, MACD, OBV)
  → WaveChannelBuilder.build(wave_count, ohlcv) → WaveChannel
  → DivergenceDetector.detect(ohlcv, pivots, oscillators) → list[DivergenceSignal]
```

## Interface Contract

### WaveChannelBuilder

```python
class WaveChannelBuilder:
    def build(self, wave_count: WaveCount, df: pd.DataFrame) -> WaveChannel | None: ...

@dataclass
class ChannelLine:
    start_idx: int
    end_idx: int
    prices: pd.Series  # channel line prices aligned to df.index

@dataclass
class WaveChannel:
    base_line: ChannelLine    # connects W1-W3 peaks/troughs
    parallel_line: ChannelLine  # projected from W4 through W5 target
    w5_target: float          # price at parallel line intersection
    channel_width: float      # base to parallel distance
```

### DivergenceDetector

```python
class DivergenceDetector:
    def __init__(self, oscillators: list[str] = ["rsi_14", "macd_histogram", "obv"]) -> None: ...
    def detect(self, df: pd.DataFrame, pivots: pd.DataFrame) -> list[DivergenceSignal]: ...

@dataclass
class DivergenceSignal:
    bar_idx: int
    divergence_type: Literal["bullish", "bearish"]
    oscillator: str        # which oscillator showed divergence
    price_trend: str       # "higher_high" or "lower_low"
    osc_trend: str         # opposite of price_trend
    confidence: float      # 0.0-1.0
```

## Constraints (RFC 2119)

- C-012: `WaveChannelBuilder` MUST return `None` when fewer than 3 impulse pivots are available (insufficient data for channel construction).
- C-013: The base channel line MUST connect Wave 1 and Wave 3 swing extremes; the parallel line MUST be offset by the channel width from the opposite extreme (Wave 2 or Wave 4).
- C-014: `DivergenceDetector` MUST require at least 2 consecutive pivots of the same type (swing highs or swing lows) to establish a divergence pattern.
- C-015: Divergence signals MUST include a `confidence` field computed from the angle of divergence (steeper oscillator divergence yields higher confidence).
- C-016: The existing `wave_momentum_divergence()` function MUST remain backward-compatible; `DivergenceDetector` wraps and extends it.

## Test Approach

- **Unit**: Test `WaveChannelBuilder` with a synthetic 5-wave impulse; verify that the parallel line projection falls within 2% of Wave 5 peak. Test `DivergenceDetector` with fabricated RSI divergence data.
- **Edge cases**: Wave 3 shorter than Wave 1 (violated iron rule) — channel MUST still be constructible but flagged with reduced confidence. Missing oscillator columns — `DivergenceDetector` MUST skip unavailable oscillators gracefully.
- **Integration**: Combine with F-001 WaveClassifier output; verify that divergence signals align with Wave 5 endpoints in historical BTC/USDT data.

## TODOs

- Determine the exact confidence formula for divergence detection (angle-based vs. magnitude-based).
- Specify whether channel projection extends indefinitely or truncates at a maximum bar distance.
- Evaluate whether volume divergence requires normalization (relative volume vs. absolute).
