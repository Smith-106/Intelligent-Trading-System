# W20 — BBO poll + CVD proxy + Elliott WFO smoke

**Date**: 2026-08-10  
**Scope**: W20a + W20b + W20c  
**Parent**: [w19-invalidation-bbo-volume.md](./w19-invalidation-bbo-volume.md) · [option-b-evolution-roadmap.md](./option-b-evolution-roadmap.md)  
**Constraint**: defaults off; no B0 fill change; smoke ≠ GO  

---

## Delivered

### W20a — Ticker BBO auto poll

| 项 | 实现 |
|----|------|
| Config | `ExecutionConfig.bbo_poll_enabled=false`, `bbo_poll_interval_s=5.0` |
| Loop | `TradingSession._bbo_poll_loop` → `fetch_ticker` → `push_ticker_bbo` |
| Start | 若 enabled → `set_bbo_source("ticker")` + spawn task |
| Stop | cancel poll task |
| Inject | `session._bbo_fetcher` for tests / custom fetcher |
| 默认 | **关**；不自动开 `orderbook_fill` |

### W20b — Bar-level CVD proxy

| 项 | 实现 |
|----|------|
| `volume.cvd_proxy` | `sign(Δclose) * volume` 累积 |
| Engine | `batch_calculate` / `compute_all` / `CLASSICAL_EXTENDED_NAMES` |
| 声明 | **非** trade-tape CVD；不可声称 aggressor 保真 |

### W20c — Elliott WFO smoke

| 项 | 实现 |
|----|------|
| 模块 | `quantflow/strategy/research/elliott_wave_wfo_smoke.py` |
| 输出 | `ElliottWfoSmokeReport`：`is_smoke=True`, `promotion_eligible=False`, `execution_path=vectorized_smoke` |
| 数据 | synthetic 默认；`parquet_dir` + symbol 可加载真实 OHLCV |
| 晋级 | **明确不可**用于 W14 register/GO |

```python
from quantflow.strategy.research.elliott_wave_wfo_smoke import run_elliott_wfo_smoke
report = run_elliott_wfo_smoke(n_bars=800, n_windows=3)
# real:
# report = run_elliott_wfo_smoke(symbol="BTC/USDT", parquet_dir="data/parquet", n_windows=3)
```

---

## Tests

```bash
pytest tests/unit/test_w20_bbo_poll_cvd_wfo.py \
  tests/unit/test_w19_invalidation_bbo_volume.py \
  tests/unit/test_indicators.py \
  tests/unit/test_w18_wave_bbo_factors.py -q
```

**Result**: 34 passed (W20 suite + regressions).

---

## Non-goals

- 默认开启 poll 或 orderbook_fill  
- 真实 trade CVD / L2 imbalance  
- 将 WFO smoke 数字写入 GO 报告  

---

*W20 complete when tests green and roadmap §W20 checked.*
