# Candidate Baseline-5 results — B5-ABL-20260810

**Contract ID**: `B5-ABL-20260810`  
**Ran at**: 2026-08-10 (UTC)  
**Runner**: `python scripts/run_baseline5_ablation_oos.py --run-id B5-ABL-20260810`  
**Artifacts** (local, gitignored): `data/paper_replay/baseline5/B5-ABL-20260810/`  
**Verdict**: **KEEP_BASELINE_0** (frozen)  
**Upgrade**: **false** · **promotion_eligible**: **false**

---

## 1. Executive summary

| Item | Value |
|------|--------|
| Probe thr | **0.0004** (B4 family; B3 0.001 untouched) |
| Data status | **NARROWED** 2024-01-01 → 2026-08-04 |
| Funding | **315** pts · max\|rate\|=**0.0005** |
| Sealed siblings | B3 / B4-OOS-20260810 **not modified** |

| Cell | EMA | OI | full orders @0.1% | full ret% | OOS meanSh |
|------|-----|-----|-------------------|-----------|------------|
| classic | — | — | 236 | −0.02 | −1.46 |
| b5_ema_on_oi_on | on | on | **0** | 0 | n/a |
| b5_ema_off_oi_on | **off** | on | **0** | 0 | n/a |
| b5_ema_on_oi_off | on | **off** | **348** | **−6.05** | −0.78 |
| b5_ema_off_oi_off | **off** | **off** | **350** | **−5.87** | −0.76 |

**Conclusion**:

1. **OI confirmation is the binding fill gate** under this meta series — EMA-off alone still yields **0** orders when OI is required.  
2. **OI-off unlocks fills** (~350) but **destroys cost-honest performance** (≈−6% full, negative OOS Sharpe) vs classic control.  
3. Therefore ablation evidence **supports KEEP_B0**, not UPGRADE. B3/B4 freezes remain correct; B5 is a sealed negative / costly-positive-fill result.

---

## 2. Interpretation

| Hypothesis | Result |
|------------|--------|
| B4 zero-fill was only EMA smoothing | **Rejected** — EMA-off + OI-on still 0 fills |
| B4 zero-fill was OI filter | **Supported** — OI-off produces hundreds of fills |
| OI-off is a GO path | **Rejected** — large negative return at 0.1%/0.1% |

---

## 3. Discipline

| Rule | Status |
|------|--------|
| No write to baseline3/ | ✅ |
| No write to baseline4/B4-OOS-* | ✅ |
| `funding_rate.yaml` thr=0.001 | ✅ unchanged |
| B4 overlay thr=0.0004 | ✅ unchanged |
| Catalog defaults `use_rate_ema`/`require_oi_confirmation` | ✅ still **true** |
| Independent run_id under baseline5/ | ✅ |

---

## 4. Reproduce

```bash
python scripts/run_baseline5_ablation_oos.py --run-id B5-ABL-20260810
pytest tests/unit/test_b5_ablation_contract.py -q
```

---

*B5-ABL-20260810 sealed KEEP_BASELINE_0 — OI-off fills are cost-negative evidence, not promotion fuel.*
