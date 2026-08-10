# Baseline-3 W15 re-run — denser funding/OI

**Date**: 2026-08-10  
**Task**: W15 (Option B)  
**Contract**: [Candidate-Baseline-3.md](./Candidate-Baseline-3.md) — **params unchanged**  
**Parent freeze**: T027 `KEEP_BASELINE_0`  
**Artifacts**: `data/paper_replay/baseline3/20260810_w15/` (**new dir; does not overwrite T026 root**)

---

## 1. Data densification (T031-style)

| Source | Funding n | OI n | Span (approx) |
|--------|-----------|------|----------------|
| T026 `s3_verify/raw` | 63 | 500 | 2024-01 → 2025-05 |
| OKX `download-funding` 90d → `data/parquet` | 270 | — | → 2026-08-10 |
| OKX `download-oi` 1H → `data/parquet` | — | 720 | ~30d cap + merge |
| **Merged** (`meta_merged` + multi-root) | **315** | **1073** | **2024-01-01 → 2026-08-04/10** |

OKX funding history API ≈ **90d window** per pull; denser long history requires **incremental accumulation** over time (already noted in CLI). This run merges historical s3_verify with fresh parquet backfill.

Runner change: `--meta-root` **merges** all roots (dedupe by timestamp), no longer first-hit break.

---

## 2. Results (contract params)

`entry_threshold=0.001`, nested, fee 0.1%/0.1%, BTC-only.

| Label | Full ret% @0.1% | Full Sh | OOS (50/50 fold) | Orders |
|-------|-----------------|---------|------------------|--------|
| classic | ≈0.0 | ≈0.01 | −2.70% / Sh≈−1.46 | 236 |
| **funding_rate** | **0** | n/a | 0 / n/a | **0** |

**Measured max |funding_rate| on merged series: still 0.0005 &lt; 0.001** → **zero entries** under frozen contract thresholds.

Fee×slip (classic): zero-cost positive; 0.1% ≈ flat; 0.2% negative — cost law still bites.

**Wave-C adjudication**: **KEEP_BASELINE_0** · upgrade=false

---

## 3. Interpretation

| Claim | Valid? |
|-------|--------|
| “Denser data fixes B3 alpha” | **No** — more points, still no threshold fires |
| “Architecture broken” | **No** — classic path still trades; funding path correctly silent |
| “Change threshold to 0.0003 for GO” | **Only via new contract (B4+)** — not silent B3 edit |
| T027 freeze superseded? | **No** — W15 **confirms** KEEP with better meta |

WFO 24m/6m still **1 segment fallback** (50/50) on effective window — not full multi-fold pin.

---

## 4. Reproduction

```bash
# refresh recent meta (OKX ~90d funding)
python -c "from quantflow.cli.main import app; app()" download-funding --symbol BTC/USDT --days 90
python -c "from quantflow.cli.main import app; app()" download-oi --symbol BTC/USDT --days 180 --period 1H

python scripts/run_baseline3_challenger.py \
  --meta-root data/meta_merged \
  --meta-root data/s3_verify/raw \
  --meta-root data/parquet \
  --out-dir data/paper_replay/baseline3/20260810_w15
```

---

## 5. Next (W15 residual / W16)

| Item | Action |
|------|--------|
| Continue incremental funding pulls | Weekly `download-funding` to grow history |
| Threshold / family change | **Candidate-Baseline-4** new contract only |
| Paper ops streak | Unrelated; keep daily Path A |

*W15: denser meta, same KEEP — evidence strengthened, not overturned.*
