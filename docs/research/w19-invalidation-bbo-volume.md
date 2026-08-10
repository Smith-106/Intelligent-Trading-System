# W19 — Invalidation wire + ticker BBO + volume factors

**Date**: 2026-08-10  
**Scope**: W19a + W19b + W19c (roadmap W19+ candidates)  
**Parent**: [w18-wave-bbo-factors.md](./w18-wave-bbo-factors.md) · [option-b-evolution-roadmap.md](./option-b-evolution-roadmap.md)  
**Constraint**: B0 default slip/fill byte-stable; `orderbook_fill` still default OFF  

---

## Delivered

### W19a — Invalidation / RSI / FeatureStore write protection

| 项 | 实现 |
|----|------|
| `WaveInvalidationChecker` 接线 | `LiuYudongWaveStrategy` 构造注入；`generate_signals` 在 hard breach 时对窗末 bar 打 exit |
| `on_bar` 桥接 | 累计 bar → `generate_signals` → 可选 `emit_signal`（结束空 stub） |
| RSI 背离参考点 | 相对 **W1 峰值** 回撤 ≥50% 且 W2 RSI > W1-peak RSI（不再用 W1 origin） |
| `save_features` | `drop_duplicates(keep="first")` + 冲突 warning（existing 胜出，防后写覆盖 PIT） |
| YAML | `use_invalidation_exits` / `max_consecutive_stops` |

### W19b — 真实 ticker BBO 入口

| 项 | 实现 |
|----|------|
| `TradingSession.set_bbo_source("bar_proxy"\|"ticker")` | 默认 `bar_proxy` |
| `push_ticker_bbo(symbol, bid, ask)` | 缓存 + source 模式下即时 `update_orderbook` |
| `_push_bbo_for_bar` | ticker 优先，缺省回退 bar low/high |
| 默认行为 | 无调用 set/push 时与 W18b 相同（bar 代理） |

### W19c — session VWAP + OBV slope

| 项 | 实现 |
|----|------|
| `volume.session_vwap` | UTC 日重置；无 timestamp 时退回全序列 VWAP |
| `volume.obv_slope` | `obv.diff(period)` 因果差分 |
| Engine | `batch_calculate` / `compute_all` / `CLASSICAL_EXTENDED_NAMES` |

---

## Tests

```bash
pytest tests/unit/test_w19_invalidation_bbo_volume.py \
  tests/unit/test_divergence.py \
  tests/unit/test_feature_store.py \
  tests/unit/test_indicators.py \
  tests/unit/test_w18_wave_bbo_factors.py \
  tests/unit/test_wave_signal_generator.py \
  tests/unit/test_elliott_wave_strategy_extra.py \
  tests/unit/test_indicator_engine_extra.py -q
```

**Result**: 92 passed.

---

## Files

- `quantflow/strategy/elliott_wave_strategy.py`
- `quantflow/indicators/divergence.py`
- `quantflow/data/feature_store.py`
- `quantflow/strategy/engine.py`
- `quantflow/indicators/volume.py`
- `quantflow/indicators/engine.py`
- `quantflow/config/strategies/elliott_wave.yaml`
- `tests/unit/test_w19_invalidation_bbo_volume.py`
- `tests/unit/test_divergence.py`

---

## Non-goals

- 自动轮询交易所 ticker（入口已备，调用方注入）  
- 默认开启 orderbook_fill  
- CVD / trade aggressor  
- 改 B0 合同  

---

*W19 complete when tests green and roadmap §W19 checked.*
