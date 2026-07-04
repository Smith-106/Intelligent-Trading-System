# F-007 — 多时间框架数据对齐（周线→4H→1H→15min）

> Role: subject-matter-expert | Related decisions: D4, Q4

## Architecture

Multi-timeframe (MTF) analysis is a cornerstone of wave theory: higher timeframes define the structural wave context, lower timeframes provide entry precision. This feature implements data alignment and wave-count propagation across four timeframes.

### Timeframe Hierarchy

| Level | Timeframe | Role | Wave Degree |
|---|---|---|---|
| L1 | Weekly (1W) | Structural context — which phase of the grand cycle | Primary / Intermediate |
| L2 | 4-Hour (4H) | Tactical wave count — identify impulse/correction | Minor / Minute |
| L3 | 1-Hour (1H) | Entry zone refinement — pinpoint W2/W4 end | Minuette |
| L4 | 15-Minute (15min) | Execution timing — precise entry/exit | Sub-minuette |

### Crypto 24/7 Timeframe Definition (Q4)

Traditional markets use natural-day boundaries. Crypto markets trade 24/7, making "daily" and "weekly" bars ambiguous. The resolution per Q4:

- **Weekly bar**: Starts Monday 00:00 UTC, ends Sunday 23:59 UTC. The week boundary is deterministic and timezone-independent.
- **4H bar**: Fixed UTC boundaries: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC.
- **1H bar**: Fixed UTC hourly boundaries.
- **15min bar**: Fixed UTC boundaries at :00, :15, :30, :45.

All bar timestamps MUST be stored as UTC. No local timezone conversion is permitted in the data layer.

### Wave Count Propagation Rules

Wave counts propagate top-down (higher TF -> lower TF):

1. The weekly timeframe identifies the current wave position (e.g., "in Wave 3 of Primary degree").
2. The 4H timeframe counts the sub-waves within that primary wave (e.g., "Wave 3 is in its sub-wave (iii)").
3. The 1H timeframe identifies the end of sub-wave (iv) for entry.
4. The 15min timeframe provides the exact entry bar.

Lower timeframes MUST NOT contradict higher timeframes. If a 15min count implies the weekly Wave 3 is over, the 15min count MUST be reclassified as a lower-degree sub-wave.

### Current Code Assessment

The existing `Fetcher` class (in `data/fetcher.py`) downloads data for a single timeframe. The `DataStore` (in `data/store.py`) stores Parquet data partitioned by symbol/year/month but not by timeframe. To support MTF:

- The fetcher MUST be extended to download multiple timeframes.
- The store MUST include timeframe in the partition key: `symbol/timeframe/year/month`.
- The existing `default.yaml` defines a single `timeframe` parameter. The `elliott_wave.yaml` MUST define the MTF hierarchy.

## Interface Contract

```python
@dataclass
class MTFAlignment:
    timeframes: list[str]         # ["1W", "4H", "1H", "15min"]
    current_bars: dict[str, Bar]  # latest bar per timeframe
    wave_context: dict[str, Optional[pd.DataFrame]]  # wave labels per TF

class MTFDataManager:
    def fetch_all_timeframes(
        self, symbol: str, start: str, end: str,
    ) -> dict[str, pd.DataFrame]:
        """Download data for all timeframes in the hierarchy."""

    def align_bars(
        self, data: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        """Align bars across timeframes to a single timeline (lowest TF)."""

    def propagate_wave_context(
        self, wave_labels: dict[str, pd.DataFrame],
    ) -> dict[str, str]:
        """Propagate wave context from higher TF to lower TF."""
```

## Constraints (RFC 2119)

1. All timeframe bar boundaries MUST be anchored to UTC. The weekly bar MUST start at Monday 00:00 UTC. Sub-day bars MUST align to fixed UTC hour boundaries.
2. Wave count propagation MUST be strictly top-down. A lower timeframe wave count that contradicts the higher timeframe context MUST be reclassified as a sub-wave of the higher timeframe structure.
3. The MTF data manager MUST use rolling windows rather than calendar-based aggregation for timeframes in crypto. For example, a "daily" analysis in crypto SHOULD use a 24-hour rolling window anchored to UTC midnight, not exchange-specific daily candles.
4. Data alignment MUST handle the case where lower-TF bars do not perfectly align with higher-TF bar boundaries. The alignment algorithm MUST use the higher-TF bar closing time as the boundary.
5. The system MUST NOT download all timeframes for every symbol unconditionally. Timeframe download SHOULD be driven by the active strategy configuration. Symbols not traded by the Elliott Wave strategy SHOULD NOT incur MTF download overhead.
6. When a higher timeframe wave count is invalidated (per F-005), the lower timeframe counts MUST be recalculated. Stale lower-TF counts from an invalidated higher-TF context MUST be flagged as `unreliable` until recalculated.
7. The MTF hierarchy SHOULD be configurable. The default is ["1W", "4H", "1H", "15min"] but a user MAY specify a different hierarchy (e.g., ["1D", "1H", "15min", "5min"]).
8. Bar alignment performance MUST NOT degrade linearly with the number of timeframes. The system SHOULD pre-compute alignment maps and cache them.

## Test Approach

- **Bar alignment tests**: Verify that 15min bars correctly aggregate into 1H, 4H, and weekly bars with exact UTC boundary alignment.
- **Wave propagation tests**: Set a weekly wave count, verify that 4H sub-wave counts are consistent with the weekly context.
- **Contradiction tests**: Create a 15min count that contradicts the weekly context and verify that reclassification occurs.
- **Invalidation cascade tests**: Invalidate a weekly count and verify that all lower-TF counts are flagged for recalculation.
- **Performance tests**: Measure alignment computation time for 1 year of BTC data across 4 timeframes. Target: < 5 seconds.

## TODOs

- Determine how to store MTF-aligned data in the existing Parquet partition scheme without breaking the `DataStore` interface.
- Define the `WaveContext` schema that carries higher-TF wave information into lower-TF analysis.
- Study whether OKX provides consistent bar boundaries across timeframes or whether custom aggregation is needed.
- Investigate how to handle gaps in lower-TF data (e.g., 15min data may have missing bars during low-liquidity periods).
- Design the caching strategy for MTF alignment maps to avoid recomputation on every bar.
