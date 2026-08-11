# Market research capability verification — 2026-08-11

**Purpose**: 用本地 parquet 市场数据跑通研究栈，验证系统能力（非 live promote）。  
**HEAD**: see `main` · **Version**: v0.7.0  
**Session**: `20260811-mkt-cap-verify-20260811-113906`

## Stack exercised

| Layer | Command / suite | Result |
|-------|-----------------|--------|
| Unit | focused dual-path / path_b / PIT / multi / session / promotion | **26 passed** |
| Dual-path OS | `python scripts/run_dual_path_research_os.py` | **ran** |
| Path B OOS | `python scripts/run_path_b_oos.py --n-windows 6` | **ran** |
| Multi-symbol | `python scripts/run_multi_symbol_dual_path.py --symbols BTC/USDT,ETH/USDT` | **ran** |
| Demo pack | `python scripts/demo_public_pack.py --check` | **OK** |

## Market window

- Contract window used by scripts: **2021-01-01 → 2026-08-04**
- Local `data/parquet`: present (**~300** files)
- Data source: previously downloaded OKX-style 1h (no live API required for these smokes)

## Honest outcomes (not marketing)

### Dual-path research OS

| Path | Gate (path metrics) | Notes |
|------|---------------------|--------|
| Path A (excess vs BTC overlay style) | **PASS** | excess≈**+47.09pp**, maxDD≈**69.5%** |
| Path B (TPSL metrics) | path gate **PASS** | excess≈**+3.98pp**, maxDD≈**21.1%**, wr≈0.39, payoff≈2.50 |
| Path B **validation** | **NO-GO** | `n_trials=10` (validation layer stricter) |
| Causal preflight | **PASS** | |
| `combined_score` | **absent** | side-by-side only |
| `promotion_eligible` | **false** | research-only |

Artifacts (local runtime, not committed):  
`data/paper_replay/dual_path/mkt_cap_dual_path.json` · `.md`

### Path B multi-window OOS (IMP-02)

| Field | Value |
|-------|--------|
| research_go | **GO_DISCUSS** |
| n_windows | **6** |
| n_trials_accounted | **69** (underreported=false) |
| frac_beat_btc | **0.50** |
| median_excess / median_dd | ≈1.43 / ≈8.65 |
| execution_path | **vectorized** |
| cost_attachment | fee_slip rows=2 · funding_mode=assumption |
| promotion_eligible | **false** |
| hard_bind_entry | **false** |

### Multi-symbol dual-path (IMP-04)

- Symbols: BTC/USDT + ETH/USDT · equal book 0.5/0.5 · `portfolio_traceable=true`
- `execution_path=vectorized` · `promotion_eligible=false` · no `combined_score`

## Capability conclusion

| Capability | Verified? |
|------------|-----------|
| Load multi-year OHLCV from parquet + DuckDB path | ✅ |
| Dual-path research report (A/B 分轴) | ✅ |
| Causal preflight | ✅ |
| Path B multi-window OOS + honest n_trials + cost attachment | ✅ |
| Multi-symbol side-by-side research report | ✅ |
| Fail-closed promotion / no combined score | ✅ |
| Public demo pack integrity | ✅ |
| Live promote / paper long-run | ❌ not in scope |
| Fresh OKX download (same day) | ⚠️ earlier connect fail; not required for offline research |

**Honest negative results allowed**: Path B validation **NO-GO** and OOS **GO_DISCUSS** still count as successful *system* verification — gates did not silently greenwash.

## Reproduce

```bash
set PYTHONUTF8=1
python -m pytest tests/unit/test_dual_path_report.py tests/unit/test_path_b_oos.py tests/unit/test_pit_audit.py tests/unit/test_multi_symbol_dual_path.py -q
python scripts/run_dual_path_research_os.py --out data/paper_replay/dual_path/mkt_cap_dual_path.json
python scripts/run_path_b_oos.py --n-windows 6 --out data/paper_replay/dual_path/mkt_cap_path_b_oos.json
python scripts/run_multi_symbol_dual_path.py --symbols BTC/USDT,ETH/USDT
python scripts/demo_public_pack.py --check
```
