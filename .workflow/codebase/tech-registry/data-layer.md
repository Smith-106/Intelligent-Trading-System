# TC-001 — DataLayer

| Field | Value |
|-------|-------|
| **ID** | TC-001 |
| **Type** | L1-data |
| **Features** | FT-007 (Data Layer), FT-011 (Data Quality Monitor) |
| **Last Updated** | 2026-08-05T13:40:00Z |

## Code Locations

- `quantflow/data/fetcher.py`
- `quantflow/data/cleaner.py`
- `quantflow/data/store.py`
- `quantflow/data/feature_store.py`
- `quantflow/data/redis_cache.py`
- `quantflow/data/mtf_aligner.py`
- `quantflow/data/dq_monitor.py`
- `quantflow/data/__init__.py`
- `quantflow/data/market_meta_fetcher.py`

## Exported Symbols

- `BASE_BACKOFF_S` — Retry backoff base (s)
- `CALL_TIMEOUT` — HTTP call timeout (s) for OKX requests
- `DEFAULT_TIMEFRAMES` — Default supported timeframes
- `DataFetcher`
- `DataQualityMonitor`
- `DataQualityScore`
- `DataStore`
- `FUNDING_HISTORY_COLUMNS` — Funding rate history DataFrame columns
- `FUNDING_MAX_AGE_FACTOR` — Funding max age multiplier
- `FUNDING_POLL_INTERVAL_S` — Minimum funding-rate poll interval (s)
- `FeatureStore`
- `FundingRateSnapshot` — Funding rate snapshot dataclass
- `InMemoryStateStore` — DQ monitor in-memory state store (fallback when Redis unavailable, v0.3.1)
- `MAX_HISTORY_PAGES` — Max fetch-history pages
- `MAX_PAGINATION_PAGES` — Max pagination pages for fetch loops
- `MAX_RETRIES` — Max retries for rate-limited requests
- `MIN_ENDPOINT_INTERVAL_S` — Minimum interval between any two endpoint calls
- `MTFAligner`
- `MTFData`
- `MarketMetaFetcher` — Funding rate & open interest fetcher (T-s2-01)
- `OI_HISTORY_COLUMNS` — Open interest history DataFrame columns
- `OI_MAX_AGE_S` — Open interest max age (s)
- `OI_POLL_INTERVAL_S` — Minimum OI poll interval (s)
- `OKX_KLINE_PAGE_MAX` — OKX kline max page size
- `OpenInterestSnapshot` — Open interest snapshot dataclass
- `RATE_LIMIT_ERROR_CODE` — OKX rate limit error code
- `RedisCache`
- `RateLimiter` — Self rate-limiter for meta-data endpoints
- `TICKER_TTL` — Redis ticker cache TTL (s)
- `TIMEFRAMES` — Supported timeframe set
- `TIMEFRAME_MAP` — Timeframe alias/period mapping
- `ValidationResult`
- `clean_ohlcv`
- `validate_no_future_leak`

## Dependencies

- Upstream: `quantflow/common` (models, exceptions, config).
- Downstream consumers: see feature maps for consumer wiring.

---

*Refreshed by codebase-refresh at 2026-08-05T05:39:39Z*
