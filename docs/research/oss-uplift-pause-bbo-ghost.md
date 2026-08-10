# OSS 学习落地 — Pause / BBO age / Ghost / Preflight

**Date**: 2026-08-10  
**Sources**: `oss-binance-deribit-btc-learnings.md` + architecture-diagnosis-vs-oss  
**Scope**: 控制与运维模式，**不**引入跨所/期权产品

---

## Changes

| Pattern | Module | Default |
|---------|--------|---------|
| Multi-source pause set | `quantflow/common/pause_reasons.py` | Library only |
| KillSwitch holds `pause_reasons` | `quantflow/execution/kill_switch.py` | Adds reasons on activate |
| BBO max age reject | `PaperGateway` `bbo_max_age_sec` | **0 = off** |
| Overlay sample | `paper_orderbook_fill_overlay.yaml` | 5s when OB fill on |
| Ghost positions | `reconciliation/ghost_positions.py` | Pure report, no auto-close |
| Preflight disk | `scripts/preflight_baseline0_paper.py` | **Warn only** |

---

## Usage

```python
from quantflow.common.pause_reasons import PauseReasonSet
pauses = PauseReasonSet()
pauses.add("data_stale")
if pauses.is_paused:
    ...

from quantflow.reconciliation import find_ghost_positions
rep = find_ghost_positions(
    tracked_symbols=["BTC/USDT"],
    exchange_positions=await gateway.query_positions(),
)
if rep.has_ghosts:
    log.warning("ghosts: %s", rep.to_dict())
```

```yaml
# orderbook fill + age gate (opt-in)
execution:
  orderbook_fill_enabled: true
  orderbook_fill:
    enabled: true
    bbo_max_age_sec: 5.0
```

---

## Explicit non-goals (still)

- Deribit / multi-venue engine  
- Mixin 巨石改写六层  
- 强制 Redis  
- 默认改 B0 slip/fill

*Steal control patterns, not product shape.*
