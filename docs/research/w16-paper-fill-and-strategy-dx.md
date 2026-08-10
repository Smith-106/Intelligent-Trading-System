# W16 — Paper 盘口填充（默认关）+ 策略 DX

**Date**: 2026-08-10  
**Option B**: [option-b-evolution-roadmap.md](./option-b-evolution-roadmap.md)  
**Not**: HFT · multi-exchange · change B0 default slip  

---

## 1. Paper orderbook fill (opt-in)

| Item | Detail |
|------|--------|
| Module | `PaperGateway` |
| Default | **OFF** — last price + flat `slippage` (byte-stable) |
| Enable | `orderbook_fill_enabled: true` or `orderbook_fill.enabled: true` |
| Overlay | `quantflow/config/paper_orderbook_fill_overlay.yaml` |
| Feed | `gateway.update_orderbook(symbol, bid, ask)` |
| Fill rule | buy → **ask**, sell → **bid**; optional `extra_slippage` |
| Missing BBO | Fall back to legacy last/order price + flat slip |

```python
pg = PaperGateway({"orderbook_fill_enabled": True, "orderbook_fill": {"extra_slippage": 0.0}})
pg.update_orderbook("BTC/USDT", bid=100.0, ask=100.2)
# market buy fills ~100.2; sell ~100.0
```

**Does not** pull live OKX books automatically (no connector bloat). Session/engine can push BBO when available.

---

## 2. Strategy DX — `SimpleStrategy`

| Item | Detail |
|------|--------|
| Path | `quantflow/strategy/templates/simple.py` |
| Catalog id | `simple` |
| YAML | `quantflow/config/strategies/simple.yaml` |
| Hooks | `should_long` / `should_short` / `should_exit_long` / `should_exit_short` |
| Default rule | Long-only SMA cross (fast/slow) |
| Paths | `on_bar` + `generate_signals` share the same hooks |

```python
from quantflow.strategy.templates.simple import SimpleStrategy

class MyEdge(SimpleStrategy):
    def should_long(self, closes):
        return closes[-1] > closes[-2]  # toy example
```

Not a new PAPER-GO candidate — DX only. Promote still requires W14 path + cost gates.

---

## 3. Explicit non-goals (W16)

- Mandatory live order book for paper  
- Partial depth / queue position / latency model (Nautilus-grade)  
- Replacing `trend_following` as B0  
- RD-Agent auto-wire to live (still W16 residual / later)

---

## 4. Tests

```bash
pytest tests/unit/test_paper_orderbook_fill.py tests/unit/test_simple_strategy.py -q
```

*W16: optional fidelity + thinner DX; architecture unchanged.*
