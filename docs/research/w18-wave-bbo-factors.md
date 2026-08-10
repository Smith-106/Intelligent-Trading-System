# W18 — Wave fidelity + BBO feed + dormant factors

**Date**: 2026-08-10  
**Scope**: W18a + W18b + W18c (combined)  
**Parent**: [w17-small-team-edge.md](./w17-small-team-edge.md) · [option-b-evolution-roadmap.md](./option-b-evolution-roadmap.md)  
**Constraint**: B0 default slip/fill byte-stable; `orderbook_fill` still default OFF  

---

## Delivered

### W18a — 波浪保真

| 项 | 实现 |
|----|------|
| 真 high/low pivot | `LiuYudongWaveStrategy._detect_pivots` → `ZigZagIndicator.compute_pivot_sequence`（不再用 marker+close 主路径） |
| confirmed pivots | `PivotSequence.confirmed_pivots` / `with_confirmed_only`；策略默认 `require_confirmed_pivots=true` |
| low-consensus 显式 | `PivotSequence.degraded` + `consensus_n`；策略默认 `allow_degraded_consensus=false`（跳过 degraded 窗） |
| legacy helper | `_extract_pivots` 仍保留，但 high/low 优先于 close |
| YAML | `elliott_wave.yaml` 增加两开关 |

### W18b — BBO feed

| 项 | 实现 |
|----|------|
| Gateway 合同 | `GatewayBase.update_orderbook` no-op |
| ExecutionEngine | `update_orderbook` 转发到 gateway |
| TradingSession bar 路径 | `on_bar` 推送 `bid=bar.low, ask=bar.high`（`mid_to_last=False`） |
| Fill 默认 | **不变**：仅 `orderbook_fill.enabled` 时用 BBO；否则 last+flat slip |

> Bar low/high 是 **代理 BBO**（非真实 top-of-book）。真实 ticker/orderbook feed 可后续替换同一 `update_orderbook` 入口。

### W18c — 休眠因子暴露

| 项 | 实现 |
|----|------|
| 接线 | dema_20, supertrend(+direction), stochrsi_k/d, kc_*, dc_* → `batch_calculate` + `compute_all` |
| 口径 | `CLASSICAL_CORE_NAMES` (21) + `CLASSICAL_EXTENDED_NAMES` + `WAVE_FACTOR_NAMES` (6, discovery-only) |
| 非目标 | wave 六因子仍不进 batch（需 wave_count） |

---

## Tests

```bash
pytest tests/unit/test_w18_wave_bbo_factors.py \
  tests/unit/test_zigzag_extra.py \
  tests/unit/test_indicators.py \
  tests/unit/test_indicator_engine_extra.py \
  tests/unit/test_paper_orderbook_fill.py \
  tests/unit/test_elliott_wave_strategy_extra.py \
  tests/unit/test_oss_uplift.py -q
```

**Result (W18)**: 66 passed.

---

## Files touched

- `quantflow/indicators/zigzag.py`
- `quantflow/strategy/elliott_wave_strategy.py`
- `quantflow/config/strategies/elliott_wave.yaml`
- `quantflow/execution/gateway_base.py`
- `quantflow/execution/engine.py`
- `quantflow/strategy/engine.py`
- `quantflow/indicators/engine.py`
- `tests/unit/test_w18_wave_bbo_factors.py` (new)
- `tests/unit/test_indicators.py` (core factor count assert)

---

## Non-goals (unchanged)

- 全深度 / 队列 / HFT  
- 默认开启 orderbook_fill  
- 改 B0 合同数字  
- 跨所 / 期权 / 换引擎  

---

*W18 implementation complete when tests green and this doc + roadmap §W18 checked.*
