# W21 — Funding risk gate + Elliott paper_replay + trades CVD scaffold

**Date**: 2026-08-10  
**Scope**: W21a + W21b + W21c  
**Parent**: [w20-bbo-poll-cvd-wfo.md](./w20-bbo-poll-cvd-wfo.md) · [option-b-evolution-roadmap.md](./option-b-evolution-roadmap.md)  
**Constraint**: defaults off; smoke ≠ auto-GO; funding is **risk** not alpha  

---

## Delivered

### W21a — Funding risk gate

| 项 | 实现 |
|----|------|
| Pure eval | `quantflow/signal/funding_risk_gate.py` — `evaluate_funding_risk` |
| Config | `RiskConfig.funding_risk_gate_enabled=false`, `max_funding_rate_abs=0.001`, `funding_risk_gate_kill=false` |
| Session | `_risk_pauses` (PauseReasonSet); `_apply_funding_risk_gate` on meta funding poll + `note_funding_rate` |
| Block path | `_process_signal_inner`: soft pause blocks **new entries** only (FLAT still closes) |
| Hard path | optional `funding_risk_gate_kill` → `KillSwitch.activate` |
| Missing rate | fail-closed when gate enabled |

### W21b — Elliott paper_replay smoke

| 项 | 实现 |
|----|------|
| Resolve | `paper_replay._resolve_strategy_class` supports `liu_yudong_wave` |
| Module | `elliott_paper_replay_smoke.py` → `build_session` + `replay` |
| Meta | `execution_path=paper_replay`, `promotion_eligible=false`, `is_smoke=true` |

```python
import asyncio
from quantflow.strategy.research.elliott_paper_replay_smoke import run_elliott_paper_replay_smoke
report = asyncio.run(run_elliott_paper_replay_smoke(n_bars=200))
```

### W21c — Trades CVD scaffold

| 项 | 实现 |
|----|------|
| `DataFetcher.fetch_trades` | returns timestamp/price/amount/side DataFrame |
| `volume.cvd_from_trades` | signed cumulative from sides |
| Fallback | still use `cvd_proxy` when no trades |

---

## Tests

```bash
pytest tests/unit/test_w21_funding_paper_cvd.py tests/unit/test_w20_bbo_poll_cvd_wfo.py -q
```

**Result**: 23 passed (W21 + W20 regression).

---

## Non-goals

- Default-on funding gate or kill  
- Auto promote Elliott paper_replay  
- Continuous trade stream / WS CVD store  

---

*W21 complete when tests green and roadmap §W21 checked.*
