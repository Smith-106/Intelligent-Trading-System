# 向幻方/闭源顶流收敛 — 2026-08-10 可度量进展

**Goal**: 盈利能力 + 风险控制向闭源顶流靠近，向幻方靠近  
**原则**（knowhow）: 借鉴**生产方式**（研究闭环 / 数据 / 三层策略池：因子→策略→风险预算+熔断），**不**复制万卡/FPGA  
**产品及格线**（已采纳）: 跨周期总回报相对 **BTC HODL**；PAPER-GO ≠ 战胜持币  

---

## 1. 本轮交付（代码 + 证据）

| 组件 | 路径 | 作用 |
|------|------|------|
| **Benchmark excess** | `quantflow/strategy/research/benchmark_excess.py` | 强制 `strategy − HODL`、IR、product gate |
| **三层账本风险预算** | `quantflow/signal/book_risk_budget.py` | factor sleeve → strategy → book gross/net + DD kill |
| **Beta+overlay 评估器** | `scripts/run_btc_beta_overlay_eval.py` | BTC beta 袖 + 有限 overlay；vs B0；成本矩阵 |
| **单测** | `tests/unit/test_benchmark_excess_book_budget.py` | **6 passed**（+ risk_metrics 合计 25） |

### 复现

```bash
export PYTHONUTF8=1
python -m pytest tests/unit/test_benchmark_excess_book_budget.py -q
python scripts/run_btc_beta_overlay_eval.py --sweep --fee 0.0002 --slip 0.0002 \
  --out data/paper_replay/beta_overlay/eval.json
```

---

## 2. 盈利能力：相对 B0 的收敛（同 pin 2021-01-01→2026-08-04）

| 路径 | 全窗收益 | vs BTC HODL | 产品门 (excess>0) |
|------|---------:|------------:|-------------------|
| BTC HODL | **+118.54%** | 0 | — |
| **B0 shared RP**（旧主路径） | **+5.14%** | **−113.4 pp** | **FAIL** |
| **Beta+overlay**（maker-like 2bp+2bp，sweep 最优） | **+125.06%** | **+6.52 pp** | **PASS** |
| Beta+overlay zero cost | +132.5% 级 | **+14.0 pp** | PASS |
| Beta+overlay **taker 10bp+10bp** | 弱于 HODL | **约 −21 pp**（w=0.25 reduce_off） | **FAIL** |

**收敛幅度**: 相对 BTC 的超额从 B0 的 **−113 pp** 提升到 maker 路径 **+6.5 pp**（同窗、可复现脚本）。  
**诚实边界**: 在 **taker 全价** 下最优结构仍可能 **FAIL** — 顶流执行/费率是 alpha 的一部分，不是文案。

最优 sweep 配置（写入 `eval.json`）:
- mode=`reduce_off`, overlay_weight=`0.25`, fee=slip=`0.0002`, MA 48/200  
- mean_exposure≈0.88（略低于满仓，换回撤与周期过滤）

---

## 3. 风险控制：幻方「三层池」映射

| 幻方组织原则 | QuantFlow 本轮落地 |
|--------------|-------------------|
| 因子库 | 既有 FactorRegistry（沿用） |
| 策略工厂 | YAML 模板 + 本轮 **beta sleeve / overlay sleeve** 显式化 |
| 风险预算 + 熔断 | **`BookRiskBudget`**: book gross/net、strategy 帽、sleeve 帽、`kill_drawdown` |
| 生产验收 | **`gate_beats_benchmark`** 与研究 PAPER-GO **分列** |

默认 highflyer-style budget: beta≤1.0、overlay≤0.20（可配）、DD kill=15%。

---

## 4. 与「闭源顶流」的差距（仍在）

| 维度 | 本轮 | 仍缺 |
|------|------|------|
| 基准诚实 | ✅ excess 强制 | 全策略产线默认挂钩 |
| 盈利路径 | ✅ beta+overlay 可过 maker 门 | 稳健 taker 后超额；多品种机构执行 |
| 风控组织 | ✅ 三层预算 API | 全链路 RiskEngine 默认装配 + 实盘对账 |
| 研究工厂 | 部分 | RD-Agent 真闭环 / 多策略自动晋级 |
| 数据 | 单所 OHLCV 为主 | 多源/微观结构 |
| 算力 | 个人机 | **不追求**万卡 |

---

## 5. 决策（写入项目）

1. **B0 不再作为「赚钱产品」旗舰**；保留为研究 OS / 管道验收基线。  
2. **产品候选叙事**转向：**BTC beta + 有限 overlay + 账本预算 + vs-HODL 门**。  
3. **费率假设必须双报**（maker_like vs taker）；仅 zero-cost PASS 不得宣传。  
4. 继续 **T023/T024** paper 墙钟 — 回测 PASS ≠ paper 晋级。  

---

## 6. 验收清单（本 goal 迭代）

- [x] 可复现 vs-BTC 超额模块  
- [x] 三层风险预算模块 + 单测  
- [x] 真数据评估脚本 + 成本矩阵  
- [x] B0 相对失败与 overlay 相对改进 **同表披露**  
- [x] 不宣称已达幻方硬件/收益规模  
- [x] RiskEngine **可选**注入 `book_risk_budget`（默认 None=旧行为；单测覆盖 kill）  
- [x] `RiskConfig.book_risk_budget` + `default.yaml` 开关（**默认 false**）经 TradingSession 装配  
- [ ] 后续：产品档默认 `enabled: true`；paper 日课挂 excess 报表  

---

*向顶流收敛 = 组织原则 + 可度量超额 + 成本诚实；不是文案对齐。*
