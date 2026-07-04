# F-007 — 多时间框架数据对齐（周线→4H→1H→15min）

> Role: system-architect | Related decisions: D1, D4

## Architecture

### Module Layout

Multi-timeframe (MTF) data alignment extends L1 (data layer) with a new component `MTFAligner` that coordinates data fetching and alignment across timeframes. Per D4, this reuses the existing `DataFetcher` and adds alignment logic.

```
quantflow/data/fetcher.py             # L1 — existing DataFetcher (reused)
quantflow/data/mtf_aligner.py         # L1 — NEW: MTFAligner + timeframe hierarchy
quantflow/data/feature_store.py       # L1 — extended for MTF feature storage
```

### Timeframe Hierarchy

The MTF hierarchy for Elliott Wave analysis follows the "top-down" principle:

| Level | Timeframe | Role | Update Frequency |
|-------|-----------|------|------------------|
| L1 | Weekly (1w) | Grand supercycle / Supercycle | Daily |
| L2 | 4H | Primary / Intermediate | Per bar (4H) |
| L3 | 1H | Minor / Minute | Per bar (1H) |
| L4 | 15min | Minuette / Subminuette | Per bar (15min) |

### Alignment Strategy

The alignment uses **time-point-safe** aggregation: higher timeframe data is only available after the bar closes. For example, the weekly wave count is only updated after Sunday 23:59 UTC close.

To address Q4 (24/7 crypto markets), the system uses UTC timestamps and rolling windows rather than natural day/week boundaries where necessary.

### Data Flow

```
DataFetcher.fetch_ohlcv(symbol, "1w") → weekly_df
DataFetcher.fetch_ohlcv(symbol, "4h") → 4h_df
DataFetcher.fetch_ohlcv(symbol, "1h") → 1h_df
DataFetcher.fetch_ohlcv(symbol, "15m") → 15m_df

MTFAligner.align([weekly_df, 4h_df, 1h_df, 15m_df]) → MTFDataFrame
MTFAligner.propagate_wave_count(weekly_wave, 4h_df) → 4h_wave_context
```

## Interface Contract

### MTFAligner

```python
class MTFAligner:
    TIMEFRAME_HIERARCHY: ClassVar[list[str]] = ["1w", "4h", "1h", "15m"]

    def __init__(self, config: MTFConfig) -> None: ...
    def align(self, dfs: dict[str, pd.DataFrame]) -> MTFDataFrame: ...
    def get_parent_context(self, symbol: str, timeframe: str, timestamp: int) -> WaveCount | None: ...
    def propagate_signal(self, signal: Signal, higher_tf_wave: WaveCount) -> Signal: ...

@dataclass
class MTFConfig:
    timeframes: list[str] = ["1w", "4h", "1h", "15m"]
    alignment_mode: Literal["closed_only", "rolling"] = "closed_only"
    rolling_window_bars: int = 168  # 7 days of hourly bars for weekly approximation
```

### MTFDataFrame

```python
@dataclass
class MTFDataFrame:
    symbol: str
    primary_timeframe: str  # e.g. "4h" for trading
    dfs: dict[str, pd.DataFrame]  # timeframe → DataFrame
    aligned_index: pd.DatetimeIndex  # unified timestamp index

    def get(self, timeframe: str) -> pd.DataFrame: ...
    def resample_to(self, target_timeframe: str) -> pd.DataFrame: ...
```

### Timeframe-Aware Wave Count

```python
@dataclass
class MTFWaveCount:
    symbol: str
    timestamp: int
    counts: dict[str, WaveCount]  # timeframe → WaveCount
    alignment_score: float  # 0.0-1.0, how well counts align across TFs
```

## Constraints (RFC 2119)

- C-033: `MTFAligner` MUST use UTC timestamps exclusively; local time conversions MUST NOT affect alignment logic.
- C-034: Higher timeframe wave counts MUST NOT be updated until the bar is confirmed closed (e.g., weekly count updates only after Sunday 23:59 UTC).
- C-035: In `rolling` alignment mode, the system MUST use a fixed number of bars (e.g., 168 hours for weekly approximation) rather than calendar weeks.
- C-036: `propagate_signal()` MUST enrich signals with higher timeframe context; a signal against the higher timeframe trend MUST have reduced strength.
- C-037: The `MTFDataFrame.aligned_index` MUST be the intersection of all timeframe indices, ensuring no extrapolation.

## Test Approach

- **Unit**: Test alignment with synthetic data where higher TF bars close at known times; verify that lower TF data is not visible before higher TF close. Test rolling window calculation.
- **Integration**: Fetch real BTC/USDT data across all 4 timeframes; verify that weekly wave count is only available after Sunday close. Test signal propagation from weekly to 15min.
- **Edge cases**: Missing data for one timeframe (e.g., 1h gap) — `MTFAligner` MUST proceed with available timeframes and log a warning.

## TODOs

- Define the exact `alignment_score` formula for `MTFWaveCount` (how to measure cross-timeframe consistency).
- Specify whether `rolling` mode is the default for crypto or if `closed_only` is preferred.
- Determine how MTF data is stored in FeatureStore (separate parquet files per timeframe vs. unified schema).
