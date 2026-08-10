# Candidate Baseline-5 — Funding EMA-off / OI-off ablation

**Status**: **CONTRACT + OOS package** (independent of W-waves)  
**Contract ID**: `B5-ABL-20260810`  
**Date**: 2026-08-10  
**Against**: [Baseline-0](./Candidate-Baseline-0.md)（唯一 **PAPER-GO**）  
**Does not supersede**: [B3](./Candidate-Baseline-3.md) · [B4](./Candidate-Baseline-4.md) (both **FROZEN KEEP_B0**)

---

## 1. Why B5 exists

B3 thr=0.001 and B4 thr=0.0004 both sealed **0 funding fills** under
`rate_ema_period=8` + OI confirmation. B4 results called out two filters that
can suppress entries even when raw max \|rate\| ≥ thr:

| Filter | Default | Effect |
|--------|---------|--------|
| Rate EMA | `rate_ema_period=8` | smooths spikes → fewer extremes |
| OI confirmation | `oi_change_threshold=0.05` | requires OI co-move |

**B5** is a **new** signal-family ablation contract: same thr family as B4
(0.0004), with explicit **EMA-off** and/or **OI-off** cells. It must **not**
edit B3/B4 YAML or `baseline3/` / `baseline4/B4-OOS-*` packages.

Strategy knobs (defaults keep B3/B4 behavior):

| Param | Default | B5 cells |
|-------|---------|----------|
| `use_rate_ema` | **true** | false = raw rate level |
| `require_oi_confirmation` | **true** | false = rate-only entry |

---

## 2. Locked fields

| Field | B5 value |
|-------|----------|
| Strategy | `funding_rate` |
| `entry_threshold` | **0.0004** (same probe as B4; not B3 0.001) |
| `exit_threshold` | **0.00015** |
| Ablation grid | control classic + 4 funding cells (EMA×OI on/off) |
| Book | BTC-only paper_replay |
| Costs | 0.1% fee + 0.1% slip + funding_tca |
| Optuna | **Forbidden** |
| Artifacts | `data/paper_replay/baseline5/<run_id>/` **only** |

Overlay: `quantflow/config/strategies/funding_rate_b5_overlay.yaml`  
Runner: `scripts/run_baseline5_ablation_oos.py`

---

## 3. Upgrade rule

Wave-C vs classic control; **default expected** KEEP_B0. Even if a cell
shows positive OOS, **human seal** required; never auto-promote B0.

---

## 4. Explicit bans

- Do **not** change B3/B4 frozen thresholds or re-open their adjudication  
- Do **not** write into `baseline3/` or `baseline4/B4-OOS-20260810/`  
- Do **not** flip catalog defaults `use_rate_ema` / `require_oi_confirmation`  
- Do **not** treat session `funding_risk_gate` as B5 alpha  

---

## 5. Run

```bash
python scripts/run_baseline5_ablation_oos.py --run-id B5-ABL-20260810
```

Results: [Candidate-Baseline-5-results.md](./Candidate-Baseline-5-results.md) (after run).
