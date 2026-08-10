# W23 — Trades ingest + Elliott cost-grid package + B4 draft

**Date**: 2026-08-10  
**Scope**: W23a + W23b + W23c  
**Parent**: [w22-trades-contract-funding-tracks.md](./w22-trades-contract-funding-tracks.md) · [option-b-evolution-roadmap.md](./option-b-evolution-roadmap.md)  
**Constraint**: defaults off; no auto-GO; B3 frozen; B4 draft only  

---

## Delivered

### W23a — Trades poll / push → TradesStore

| 项 | 实现 |
|----|------|
| `TradesIngestLoop` | REST poll + `push_trades` (WS-style) |
| Config | `trades_poll_enabled=false`, interval 30s, `data/trades` |
| Session | `TradingSession` start/stop 接线（默认关） |
| Adapter | `make_fetcher_adapter(DataFetcher)` |

```yaml
execution:
  trades_poll_enabled: true
  trades_poll_interval_s: 30
  trades_store_dir: data/trades
```

### W23b — Elliott cost-grid package

| 项 | 实现 |
|----|------|
| 模块 | `elliott_cost_grid_contract.py` |
| Grid | 0/0 + 0.1%/0.1% + 0.2%/0.2%（proxy_from_fills） |
| TCA | `funding_tca` mode=assumption |
| Checks | `require_cost_grid` + `require_funding_tca` + W14 path |
| Decision | 强制 `NO_GO` / `promotion_eligible=false` |

```python
import asyncio
from quantflow.strategy.research.elliott_cost_grid_contract import build_elliott_cost_grid_package
pkg = asyncio.run(build_elliott_cost_grid_package(n_bars=200, output_dir="data/paper_replay/elliott_w23"))
assert pkg.cost_check["passed"] and pkg.path_check["passed"]
assert pkg.promotion_eligible is False
```

### W23c — B4 funding contract (no B3 edit)

| 项 | 实现 |
|----|------|
| Doc | [Candidate-Baseline-4.md](./Candidate-Baseline-4.md) — DRAFT NOT RUN |
| Overlay | `funding_rate_b4_overlay.yaml` thr=**0.0004** |
| Index | `baseline-contract-index.md` 登记 B4 |
| 禁令 | 不改 `funding_rate.yaml` 默认 0.001；不写 `baseline3/` |

---

## Tests

```bash
pytest tests/unit/test_w23_trades_cost_b4.py tests/unit/test_w22_trades_contract_funding_tracks.py -q
```

**Result**: 15 passed.

---

## Non-goals

- 生产级 trades WS 总线  
- B4 challenger 自动跑数 / 晋级  
- 用 cost proxy 冒充密封 GO  

---

*W23 complete when tests green and roadmap §W23 checked.*
