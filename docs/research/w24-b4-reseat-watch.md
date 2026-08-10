# W24 — B4 runner + Elliott reseat cost grid + watch_trades

**Date**: 2026-08-10  
**Scope**: W24a + W24b + W24c  
**Parent**: [w23-trades-cost-b4.md](./w23-trades-cost-b4.md) · [option-b-evolution-roadmap.md](./option-b-evolution-roadmap.md)  
**Constraint**: never write `baseline3/`; no auto-GO; B3 frozen  

---

## Delivered

### W24a — B4 challenger runner

| 项 | 实现 |
|----|------|
| Script | `scripts/run_baseline4_challenger.py` |
| Out dir | **only** `data/paper_replay/baseline4/` (refuses `baseline3`) |
| Modes | `--dry-run` · `--synthetic` (default smoke) |
| Params | thr=**0.0004** (B3 ref 0.001 frozen) |
| Artifacts | `run_meta.json` / `adjudication.json` / `funding_tca.json` / `summary.json` |
| Verdict | default `KEEP_BASELINE_0` · `promotion_eligible=false` |

```bash
python scripts/run_baseline4_challenger.py --dry-run
python scripts/run_baseline4_challenger.py --synthetic --out-dir data/paper_replay/baseline4/smoke
```

### W24b — Elliott multi-run reseat cost grid

| 项 | 实现 |
|----|------|
| Default | `build_elliott_cost_grid_package(reseat=True)` |
| Method | each fee×slip cell → independent `paper_replay` |
| Fallback | `reseat=False` → W23b `proxy_from_fills` |
| Decision | still **NO_GO** / not promotion_eligible |

### W24c — watch_trades scaffold

| 项 | 实现 |
|----|------|
| `DataFetcher.watch_trades` | ccxt.pro when present; else REST poll fallback |
| `attach_watch_trades` | wire stream → `TradesIngestLoop.push_trades` |
| Default | off (caller starts stream) |

---

## Tests

```bash
pytest tests/unit/test_w24_b4_reseat_watch.py tests/unit/test_w23_trades_cost_b4.py -q
```

**Result**: 15 passed.

---

## Non-goals

- Full B4 OOS meta challenger (parquet denser funding) as sealed UPGRADE  
- Claiming reseat grid is B0-class GO  
- Production multi-stream WS bus  

---

*W24 complete when tests green and roadmap §W24 checked.*
