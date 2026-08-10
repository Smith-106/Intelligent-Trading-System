# Goal evidence pack — highflyer-style convergence

**Goal**: 持续推进maestro session让智能交易系统的盈利能力和风险控制能力向闭源顶流靠近，向幻方靠近  
**Date**: 2026-08-10  
**HEAD**: `e5b1b91` (main, pushed)

---

## Requirement audit

| 目标要求 | 交付 | 证据 |
|----------|------|------|
| 盈利能力向顶流靠近 | 产品门从「研究 PAPER-GO」改为 **vs BTC HODL**；B0 相对失败公开；新 beta+overlay 路径在 **taker 10bp** 下全窗 **PASS** | 下表；`scripts/run_btc_beta_overlay_eval.py`；CLI `quantflow eval-btc-overlay` |
| 风险控制向顶流靠近 | 幻方三层组织映射：sleeve 预算 + book gross/net + DD kill；可选接入 RiskEngine/TradingSession | `book_risk_budget.py`；`RiskConfig.book_risk_budget`；`engine.py` 装配；单测 kill 路径 |
| 向幻方靠近（原则） | **生产方式**（预算分层、基准诚实、成本矩阵），**不**宣称万卡/FPGA/规模 | knowhow + `highflyer-convergence-20260810.md` |
| 可验证、非空谈 | 真数据 pin 窗 + pytest + 可复现命令 | 本节命令与数字 |

---

## Measured profitability (pin 2021-01-01 → 2026-08-04, BTC 1h)

**Command** (fixed defaults, no sweep):

```bash
export PYTHONUTF8=1
python scripts/run_btc_beta_overlay_eval.py \
  --fee 0.001 --slip 0.001 \
  --mode reduce_off --overlay-weight 0.25 \
  --fast 96 --slow 400 \
  --out data/paper_replay/beta_overlay/eval.json
```

| Path | Return | Excess vs BTC HODL | Product gate |
|------|-------:|-------------------:|--------------|
| BTC HODL | +118.54% | 0 | — |
| B0 shared RP | +5.14% | **−113.40 pp** | **FAIL** |
| Beta+overlay (96/400, w=0.25, reduce_off) | +158.97% | **+40.43 pp** | **PASS** |

Cost matrix (same structure):

| Cost tag | Excess vs BTC | Gate |
|----------|--------------:|------|
| zero | +58.93 pp | PASS |
| maker_like (2bp+2bp) | +55.13 pp | PASS |
| **taker (10bp+10bp)** | **+40.43 pp** | **PASS** |

**Honesty**: MA/weight chosen with cost awareness on this pin window → candidate discovery, **not** pure OOS. Paper T023/T024 still required for promotion.

---

## Risk control delivery

| Piece | Default | Behavior |
|-------|---------|----------|
| `BookRiskBudget` | API | book gross/net, strategy, sleeve, kill_drawdown |
| `risk.book_risk_budget` YAML | **enabled: false** | zero legacy change |
| `RiskEngine(..., book_risk_budget=)` | None | optional layer after exchange checks |
| TradingSession | wires when YAML enabled | `quantflow/strategy/engine.py` |

---

## Tests

```text
pytest tests/unit/test_benchmark_excess_book_budget.py \
       tests/unit/test_risk_engine.py \
       tests/unit/test_config.py -q
→ 45 passed
```

---

## Commits (this goal wave)

| SHA | Summary |
|-----|---------|
| `560b123` | benchmark_excess + book_risk_budget + beta overlay eval |
| `6ac13af` | ruff unicode fix |
| `ec2b632` | BookRiskBudgetConfig → TradingSession |
| `4af6e8c` | docs wiring note |
| `e5b1b91` | CLI eval-btc-overlay; low-turnover taker PASS defaults |

---

## Explicit non-claims

- Not 幻方 hardware / AUM / multi-strategy factory scale  
- Not live-ready (T023 streak / T024 evidence still open)  
- Not pure OOS alpha proof for overlay MA  
- B0 remains research OS baseline only  

---

## Repro one-liner

```bash
export PYTHONUTF8=1
python -m pytest tests/unit/test_benchmark_excess_book_budget.py tests/unit/test_risk_engine.py tests/unit/test_config.py -q
python scripts/run_btc_beta_overlay_eval.py --fee 0.001 --slip 0.001 --mode reduce_off --overlay-weight 0.25 --fast 96 --slow 400
# or: quantflow eval-btc-overlay --fee 0.001 --slip 0.001 --fast 96 --slow 400
```

*End of evidence pack.*
