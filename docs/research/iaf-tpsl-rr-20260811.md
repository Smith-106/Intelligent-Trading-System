# IAF + TP/SL + 盈亏比（R:R）研究 — 2026-08-11

**Maestro session**: `20260811-iaf-tpsl-rr-optimize-20260811-065359`  
**Run**: `20260811-001-execute`  
**HEAD 锚点**: 见 main 本提交  

---

## 1. 目标

在已落地的 **IAF 正交指标 + 未来函数门禁** 之上：

1. 引入 **止盈 / 止损 / 最小盈亏比** 研究仿真  
2. 对比 **降回撤 / 提收益 / 胜率 / 盈亏比**  
3. 不破坏 B0/B3–B5 冻结合同；产品门仍报 vs BTC HODL  

---

## 2. 交付物

| 路径 | 说明 |
|------|------|
| `quantflow/strategy/research/tpsl.py` | `TPSLConfig`、long/flat 仿真、交易统计、dual-MA 因果 entry |
| `scripts/run_btc_tpsl_eval.py` | pin 窗评估 + sweep |
| `tests/unit/test_tpsl.py` | 单测 + entry 因果 |
| `docs/research/iaf-indicators-anti-leak-20260811.md` | 指标/防未来（前序） |

规则：

- 入场序列须 **已 lag**（`shift(1)`）  
- SL/TP 用 **入场 bar** 价格/ATR 锁定  
- 同 bar 既触 SL 又触 TP → **悲观按 SL**  
- `min_rr`：若 `tp < min_rr * sl` 自动抬升 TP  

---

## 3. 回测（BTC 1h，2021-01-01→2026-08-04，taker 10bp+10bp）

| 路径 | Return | Excess vs HODL | maxDD | 胜率 | 盈亏比 payoff | Gate |
|------|-------:|---------------:|------:|-----:|-------------:|------|
| BTC HODL | +118.54% | 0 | 77.19% | — | — | — |
| Primary overlay reduce_off w=0.30 | **+165.63%** | **+47.09 pp** | 69.47% | n/a* | n/a* | **PASS** |
| Discrete TPSL default SL3%/TP6% RR≥2 | +19.47% | −99.07 pp | **19.91%** | 37.7% | 1.85 | FAIL |
| **Recommended TPSL SL4%/TP10% RR≥2.5** | **+122.52%** | **+3.98 pp** | **21.13%** | **39.1%** | **2.50** | **PASS** |

\*连续 beta+overlay 不是离散「笔」交易，无同口径胜率。

### 解读（产品语义）

| 若优先… | 选 |
|---------|----|
| **绝对超额 / 战胜持币幅度** | 仍用 **primary overlay w=0.30**（+47pp） |
| **回撤控制 + 仍 beat HODL + 可控 R:R** | **TPSL SL4% / TP10% / min_rr=2.5**（DD ~21%，payoff~2.5） |
| 仅压回撤、可接受输 HODL | 更紧 SL/TP（如 3%/6%）— 研究用，非产品默认 |

**诚实**：离散 long/flat + 硬止损在牛市会 **切断趋势仓位**，超额通常远低于「始终带 beta 的 overlay」。两者不是同一产品。

---

## 4. 复现

```bash
export PYTHONUTF8=1
python -m pytest tests/unit/test_tpsl.py tests/unit/test_causal_oscillators.py -q

# 推荐 TPSL
python scripts/run_btc_tpsl_eval.py --sl 0.04 --tp 0.10 --min-rr 2.5 \
  --out data/paper_replay/tpsl/eval_recommended.json

# 网格
python scripts/run_btc_tpsl_eval.py --sweep --out data/paper_replay/tpsl/eval_sweep.json

# 连续超额旗舰（前序）
python scripts/run_btc_beta_overlay_eval.py --fee 0.001 --slip 0.001
```

---

## 5. 与 IAF / 过拟合

- 更多正交指标 → 后续可用 **相关剪枝 + CPCV** 选入场过滤（本轮未把 CCI/TSI 硬绑进默认 entry，避免再拟合一刀）  
- 未来函数：entry lag + 入场锁 barrier + 因果单测  
- TP/SL 参数在 pin 窗 sweep → **成本感知候选**，非独立 OOS 圣杯  

---

## 6. 一句话

> **硬 TP/SL + min R:R=2.5（4%/10%）把离散 dual-MA 路径压到 ~21% maxDD 且仍 +4pp beat HODL、payoff~2.5；要大幅超额仍靠 continuous overlay。旗舰路径分流，不混为一谈。**
