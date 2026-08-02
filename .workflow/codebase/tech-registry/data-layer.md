# TC-001 — DataLayer

| Field | Value |
|-------|-------|
| **ID** | TC-001 |
| **Type** | L1-data |
| **Features** | FT-007 (Data Layer), FT-011 (Data Quality Monitor) |
| **Last Updated** | 2026-08-02T14:30:00Z |

## Code Locations

- `quantflow/data/fetcher.py`
- `quantflow/data/cleaner.py`
- `quantflow/data/store.py`
- `quantflow/data/feature_store.py`
- `quantflow/data/redis_cache.py`
- `quantflow/data/mtf_aligner.py`
- `quantflow/data/dq_monitor.py` — `DataQualityMonitor` (real-time bar validation: freshness/price-continuity/volume-anomaly), `DataQualityScore`, `ValidationResult`
- `quantflow/data/__init__.py`

## Exported Symbols

- `DataFetcher` — CCXT async OKX fetcher (REST + WebSocket), pagination, non-finite bar rejection, `CALL_TIMEOUT`, sandbox mode.
- `DataStore` — Parquet Hive-partitioned storage (`symbol/year/month`, zstd) + DuckDB zero-copy query with path-traversal & SQL-injection guards.
- `FeatureStore` — point-in-time safe feature compute (`end=timestamp`, no future leak), Hive-mirrored save/load.
- `MTFAligner` — multi-timeframe alignment (1W→4H→1H→15m) with leak-safe HTF shift.
- `MTFData` — aligned multi-timeframe container.
- `RedisCache` — real-time ticker/bar cache with TTL; raises `DataError` when unconnected.
- `clean_ohlcv` — dedup, gap-fill, OHLC repair, outlier z-score, future-timestamp rejection.
- `validate_no_future_leak` — raises `ValueError` on future-timestamp leak.
- `DataQualityMonitor` — real-time data quality gating: freshness (60s staleness), price continuity (5% spike), volume anomaly (10x avg). Composite score (0-1, weighted 40/30/30). Prometheus metrics: `dq_monitor_violations_total`, `dq_data_staleness_seconds`, `dq_quality_score`. Redis-backed cross-process state.
- `DataQualityScore` — composite quality score dataclass (freshness/continuity/anomaly/overall).
- `ValidationResult` — bar validation result (valid flag + violations list + score).

## Dependencies

- Upstream: `quantflow/common` (models, exceptions, config).
- Downstream consumers: L2 Indicators (`IndicatorEngine`), L3 Strategy (`DataFetcher`/`FeatureStore` via `TradingSession`), L5 Execution (rare, market price).
- External: CCXT, DuckDB, pandas, Redis client.

---

*Refreshed by codebase-refresh at 2026-08-02T14:30:00Z*
