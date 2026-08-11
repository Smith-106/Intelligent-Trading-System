# Best Solution — Team Swarm Adversarial Design (IAF + TPSL)

**Session**: `20260811-team-swarm-iaf-tpsl`  
**Run**: `20260811-001-team-swarm`  
**Converged**: max_iterations=3  
**Best ant**: ANT-3-2 (score 0.400)

---

## Elite path (ACO best)

```text
N_return_excess → N_product_path_split → N_anti_overfit_validation → N_future_function_guard
```

## Dual-product recipe (do not merge)

### Path A — Flagship excess (continuous)
| Item | Value |
|------|------:|
| Profile | `primary_w30` reduce_off |
| MA | 96 / 400 |
| Overlay weight | 0.30 |
| Excess vs HODL (taker) | **+47.09 pp** |
| maxDD | ~69.5% |
| Winrate | n/a (not pen trades) |

### Path B — Drawdown / R:R control (discrete TPSL)
| Item | Value |
|------|------:|
| Entry | dual-MA lag-1 |
| SL / TP / min_rr | **4% / 10% / 2.5** |
| Excess vs HODL | **+3.98 pp** |
| maxDD | **~21.1%** |
| Winrate / payoff | **~39% / ~2.50** |

---

## Complementary elite path (control sleeve)

```text
N_future_function_guard → N_anti_overfit_validation → N_tpsl_rr_control → N_drawdown_reduce
```

1. **Causal preflight**: `shift_for_trade`, `assert_series_causal`, AST negative-shift in `validate --method lookahead`  
2. **Composite gate**: CPCV (PBO&lt;0.5) → DSR (honest n_trials) → WFO → cost matrix → vs-BTC → paper_replay  
3. **TPSL geometry**: entry-bar lock; same-bar SL before TP; reject payoff&lt;2  
4. **IAF indicators**: orthogonal library only; correlation prune + CPCV before any hard-bind; **never** silent freeze-contract edits  

---

## Adversarial conclusions (swarm consensus)

| Claim | Verdict |
|-------|---------|
| More indicators alone reduce overfit | **False** — only with prune + purged CV |
| Future-function fixes raise excess | **Indirect** — prevent fake alpha, not free return |
| Hard TP/SL raises excess vs HODL | **Usually false** on bulls; **true** for DD/R:R control |
| One score for overlay + TPSL | **Forbidden** — product path split |
| Pin-window WR optimization is safe | **False** without CPCV/PBO/WFO |

---

## Implementation already in repo

- IAF oscillators + causal: commit `b19e34f`  
- TPSL + eval: commit `3d4f6e7`  
- Overlay primary w=0.30: commit `b167eb7`  

## Next (optional engineering)

> **Implemented as plan**: [dual-path-research-os-20260811.md](./dual-path-research-os-20260811.md) (Dual-Path Research OS).

1. Wire IAF factors into a **research filter** (corr prune) — not default live entry  
2. Add CPCV/PBO report on TPSL barrier grid (honest n_trials)  
3. Dual-dashboard: Path A excess + Path B DD/R:R  
4. Keep B0/B3–B5 freezes untouched  

---

## One-liner

> **Maximize excess with continuous overlay w=0.30; control DD/R:R with discrete TPSL 4/10; gate everything with causal + CPCV/DSR/WFO/cost/vs-BTC; treat IAF as a pruneable library, not free knobs.**
