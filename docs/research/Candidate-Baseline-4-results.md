# Candidate Baseline-4 results — B4-OOS-20260810

**Contract ID**: `B4-OOS-20260810`  
**Ran at**: 2026-08-10 (UTC)  
**Runner**: `python scripts/run_baseline4_full_oos.py --run-id B4-OOS-20260810`  
**Artifacts** (local, gitignored): `data/paper_replay/baseline4/B4-OOS-20260810/`  
**Verdict**: **KEEP_BASELINE_0** (frozen)  
**Upgrade**: **false** · **promotion_eligible**: **false**

---

## 1. Executive summary

| Item | Value |
|------|--------|
| Challenger | `funding_rate` @ **entry_threshold=0.0004** (B4) |
| Control | classic `trend_following` |
| Data status | **NARROWED** to funding ∩ OHLCV |
| Effective window | **2024-01-01 → 2026-08-04** UTC |
| Funding points | **315** (merged s3_verify + parquet) |
| max \|funding_rate\| | **0.0005** |
| B4 full orders @ 0.1%/0.1% | **0** |
| Classic full orders | **236** |
| WFO | 24m/6m → **0 segments** on effective window → **single 50/50 OOS fold** |

**Conclusion**: Lowering the threshold from B3’s frozen **0.001** to **0.0004** did **not** produce funding_rate fills under the measured series + OI confirmation path. KEEP B0 is the correct sealed outcome. B3 remains frozen; B0 remains sole PAPER-GO.

---

## 2. Why still zero fills?

Measured max \|rate\| = **0.0005** > **0.0004**, so a raw level gate could fire. The strategy also applies:

1. **rate EMA** smoother (`rate_ema_period`, default 8) — peaks are diluted  
2. **OI confirmation** (`oi_lookback=3`, `oi_change_threshold=0.05`) — entries need OI co-movement  
3. **freshness / bar_hook** path on paper_replay  

Net: **0 orders** is an honest negative for this contract package, not a runner bug. A future **B5** would need a *new* written contract if humans want EMA-off or OI-off ablations — not a silent B4 edit.

---

## 3. Headline numbers (production cost 0.1% fee + 0.1% slip)

| label | full ret% | full Sharpe | full DD% | full orders | OOS mean ret% | OOS meanSh |
|-------|-----------|-------------|----------|-------------|---------------|------------|
| classic | −0.02 | 0.013 | 5.51 | 236 | −2.70 | −1.46 |
| funding_rate_b4 | 0.00 | n/a | 0.00 | **0** | 0.00 | n/a (−10 sentinel) |

### Fee×slip grid (orders)

| label | 0/0 | 0.1%/0.1% | 0.2%/0.2% |
|-------|-----|-----------|-----------|
| classic ret% | +5.44 | −0.02 | −5.19 |
| funding_rate_b4 ret% | 0 | 0 | 0 |
| funding_rate_b4 orders | 0 | 0 | 0 |

`funding_tca`: hybrid from measured series (attached in run dir).

---

## 4. Freeze discipline

| Rule | Status |
|------|--------|
| No write to `baseline3/` | ✅ |
| No edit `funding_rate.yaml` default 0.001 | ✅ |
| Independent `run_id` package | ✅ `B4-OOS-20260810` |
| adjudication_frozen.json | ✅ KEEP_BASELINE_0 |
| Not a W28 wave | ✅ independent contract ID |

---

## 5. Reproduce

```bash
python scripts/run_baseline4_full_oos.py --run-id B4-OOS-20260810
# optional freeze refresh
python scripts/freeze_baseline4_adjudication.py \
  --run-dir data/paper_replay/baseline4/B4-OOS-20260810
```

---

## 6. Parallel ops (T023) — not part of this contract

At run time (UTC **2026-08-10**):

| streak | value |
|--------|--------|
| credited UTC days | 2026-08-08, 09, 10 |
| consecutive | **3 / 7** |
| target_met | **false** |

Path A day-session preflight re-run OK; ledger re-ingested. **Do not forge** missing calendar days 08-04…08-07. Continue daily Path A until consecutive≥7 before T024 real promote evidence.

---

*B4-OOS-20260810 sealed as KEEP_BASELINE_0 — negative result is first-class evidence.*
