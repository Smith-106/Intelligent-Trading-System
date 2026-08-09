# Candidate Baseline-0 — Shared-book Symbol RP (paper)

**Status**: contract locked + **PAPER-GO** results (Wave B3, 2026-08-08)  
**Version pin**: QuantFlow `0.5.0`  
**Acceptance environment**: **paper / paper_replay only** (no trading live)

## Experiment contract (immutable for this baseline)

| Field | Locked value |
|-------|----------------|
| Strategy | `trend_following` |
| Direction gate | `nested` (4h outer + 1h inner; see paper_replay gates) |
| Entry structure | `classic` (`entry_structure=classic`) |
| Portfolio | **Shared book** + `portfolio_optimization.method=risk_parity` + **symbol-level** rebalance |
| Rebalance | every **48** unique timestamps (~2d on 1h) |
| Universe | `BTC/USDT`, `ETH/USDT`, `SOL/USDT` |
| Timeframe | `1h` |
| Window (full) | `2021-01-01` → `2026-08-04` (SOL-constrained intersection) |
| WFO | train **24** months / forward **6** months (OOS-only metrics) |
| Costs | `taker_fee=0.001` (0.1%), `slippage=0.001` (0.1%) |
| Capital | `100_000` quote |
| Research risk | `research_risk_bypass=True` on replay harness (signal/alloc isolation; cost still applied) |

## Explicit non-comparisons

- Do **not** 1:1-compare **silo** risk_parity equity to shared-book PnL.
- Do **not** treat full-window metrics alone as production evidence — **WFO OOS** is the promotion gate.
- Do **not** run full Optuna / synchronized parameter search against this baseline (Wave C allows fixed structure A/B only).

## GO thresholds (paper candidate)

All must hold on **WFO OOS summary** for `shared_risk_parity` (primary) vs contract:

1. `mean_sharpe` (OOS) **> 0**
2. `cum_return_pct` (sum of OOS segment returns) **≥ 0**
3. `mean_max_dd_pct` **≤ equal mode** on the same WFO run (RP must not worsen average DD vs equal)
4. `pos_segments / n_segments` **≥ 50%** (majority of OOS windows non-negative return)
5. Full-window shared RP `orders` **> 0** (non-degenerate)

Failing any item ⇒ **NO-GO** as production candidate; keep as research reference only.

## Reproduction

Unified entry (writes under `data/paper_replay/baseline0/`):

```bash
python scripts/run_baseline0.py
# or subset:
python scripts/run_baseline0.py --skip-full
python scripts/run_baseline0.py --skip-wfo
```

### Time-window pin + data fingerprint (T011)

Every `run_baseline0` / `multi_symbol_replay` run records in `run_meta.json` (and
replay JSON `window` / `data_fingerprint`):

| Field | Meaning |
|-------|---------|
| `start` / `end` | Contract ISO calendar (default `2021-01-01` → `2026-08-04`) |
| `start_ms` / `end_ms` | Inclusive UTC ms bounds |
| `data_fingerprint.aggregate` | Hash of per-symbol OHLCV in the pin window |
| `data_fingerprint.symbols.*.bar_count` | Bars actually used |

**Rules**

1. Defaults **require** an explicit pin (`--require-pin` true). Empty start/end → fail.
2. GO re-runs must match **same start/end** and the same `data_fingerprint.aggregate`
   (or document a deliberate data revision + re-issue gate).
3. Growing parquet **after** `end` must not change sealed narratives when the pin is kept.
4. Override window only with intent: `python scripts/run_baseline0.py --start ... --end ...`

Fingerprint helper: `quantflow.strategy.research.contract_pin`.

Underlying scripts (same locked defaults):

```bash
python scripts/multi_symbol_replay.py \
  --symbols BTC/USDT,ETH/USDT,SOL/USDT \
  --start 2021-01-01 --end 2026-08-04 \
  --gate nested --fee 0.001 --slip 0.001 \
  --out data/paper_replay/baseline0/multi_symbol_replay.json

python scripts/wfo_shared_rp.py \
  --symbols BTC/USDT,ETH/USDT,SOL/USDT \
  --start 2021-01-01 --end 2026-08-04 \
  --train-months 24 --fwd-months 6 \
  --gate nested --fee 0.001 --slip 0.001 \
  --rebalance-bars 48 \
  --out data/paper_replay/baseline0/wfo_shared_rp.json
```

## Paper operator handbook (daily session, not batch replay)

**Daily checklist (recommended entry):** [baseline0-paper-run-checklist.md](./baseline0-paper-run-checklist.md)  
**Preflight:** `python scripts/preflight_baseline0_paper.py`

Default `quantflow/config/default.yaml` keeps `portfolio_optimization.enabled: false` (zero behavior change).  
For a **paper** multi-symbol shared-RP session, use the committed overlay:

```bash
python scripts/preflight_baseline0_paper.py

quantflow run --mode paper --strategy trend_following \
  --symbols BTC/USDT,ETH/USDT,SOL/USDT \
  --timeframe 1h --interval 60 --capital 100000 \
  --config quantflow/config/paper_baseline0_overlay.yaml
```

**Path note:** daily `quantflow run` does **not** attach the research `nested` direction-gate wrapper (that lives in `paper_replay` / `run_baseline0.py`). Use path B in the checklist when comparing to `gate.json`.

Batch research remains the source of truth for GO/NO-GO numbers.

## Outputs

| Artifact | Path |
|----------|------|
| Contract (this file) | `docs/research/Candidate-Baseline-0.md` |
| Full-window multi-mode JSON | `data/paper_replay/baseline0/multi_symbol_replay.json` |
| WFO OOS JSON | `data/paper_replay/baseline0/wfo_shared_rp.json` |
| Run summary (filled after B3) | `docs/research/Candidate-Baseline-0-results.md` |

## Parameter / code anchors

- Shared multi-symbol session: `quantflow/strategy/research/paper_replay.py` (`build_multi_symbol_session`, `replay_multi`)
- Symbol RP rebalance: `quantflow/strategy/engine.py` (`portfolio_optimization`, unique-timestamp rebalance counter)
- Structure default: `quantflow/strategy/templates/trend_following.py` (`entry_structure=classic`)

## Change control

Any change to the locked table ⇒ new baseline id (`Baseline-1`, …) and a new results file.  
Do not overwrite Baseline-0 numbers in place without renaming.
