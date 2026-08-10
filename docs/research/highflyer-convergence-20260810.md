# 向幻方/闭源顶流收敛 — 2026-08-10 可度量进展

**Goal**: 盈利能力 + 风险控制向闭源顶流靠近，向幻方靠近  
**原则**（knowhow）: 借鉴**生产方式**（研究闭环 / 数据 / 三层策略池：因子→策略→风险预算+熔断），**不**复制万卡/FPGA  
**产品及格线**（已采纳）: 跨周期总回报相对 **BTC HODL**；PAPER-GO ≠ 战胜持币  
**HEAD**: `main`（见 git log：`eval-btc-overlay` / BookRiskBudget / benchmark_excess）

---

## 1. 本轮交付（代码 + 证据）

| 组件 | 路径 | 作用 |
|------|------|------|
| **Benchmark excess** | `quantflow/strategy/research/benchmark_excess.py` | 强制 `strategy - HODL`、IR、product gate |
| **三层账本风险预算** | `quantflow/signal/book_risk_budget.py` | factor sleeve → strategy → book gross/net + DD kill |
| **RiskEngine 接线** | `risk_engine.py` + `BookRiskBudgetConfig` + `default.yaml` | 可选装配（**默认 off**） |
| **TradingSession** | `quantflow/strategy/engine.py` | YAML `risk.book_risk_budget.enabled` → RiskEngine |
| **Beta+overlay 评估器** | `scripts/run_btc_beta_overlay_eval.py` | BTC beta 袖 + 有限 overlay；vs B0；成本矩阵 |
| **CLI** | `quantflow eval-btc-overlay` | 产品门一键复现 |
| **单测** | `tests/unit/test_benchmark_excess_book_budget.py` + config/risk | **45 passed**（本包相关） |

### 复现

```bash
export PYTHONUTF8=1
python -m pytest tests/unit/test_benchmark_excess_book_budget.py tests/unit/test_risk_engine.py tests/unit/test_config.py -q
python scripts/run_btc_beta_overlay_eval.py --sweep --fee 0.001 --slip 0.001 \
  --out data/paper_replay/beta_overlay/eval.json
# 或
# quantflow eval-btc-overlay --sweep --fee 0.001 --slip 0.001
```

---

## 2. 盈利能力：相对 B0 的收敛（pin 2021-01-01→2026-08-04）

| 路径 | 全窗收益 | vs BTC HODL | 产品门 |
|------|---------:|------------:|--------|
| BTC HODL | **+118.54%** | 0 | — |
| **B0 shared RP**（旧主路径） | **+5.14%** | **−113.4 pp** | **FAIL** |
| **Beta+overlay**（默认/扫参：reduce_off w=0.25, MA **96/400**, **taker 10bp+10bp**） | **+165.63%** | **+47.1 pp** | **PASS** |
| 同结构 maker-like 2bp | — | **+65.3 pp** | PASS |
| 同结构 zero cost | — | **+70.0 pp** | PASS |

**收敛幅度（产品语义）**:  
相对 BTC 超额从 B0 **−113 pp** → overlay 路径 **+47 pp（taker）**。  

### 诚实边界（必读）

1. **MA 周期与权重在同一 pin 窗上扫参** — 这是 **cost-aware 候选发现**，不是严格纯样本外。正式晋级仍须独立 hold-out / paper（T023–T024）。  
2. **仍是 BTC 周期 beta 主导** — 结构是「少亏 beta + 有限择时」，不是无 beta 的纯 alpha 工厂。  
3. **换手下降是关键** — 慢均线（96/400）把 overlay turnover 压到可承受 taker 的水平；快均线（48/200）在 taker 下曾 FAIL。  
4. **不宣称已达幻方收益规模/夏普/容量**。

---

## 3. 风险控制：幻方「三层池」映射

| 幻方组织原则 | QuantFlow 落地 |
|--------------|----------------|
| 因子库 | FactorRegistry（既有） |
| 策略工厂 | YAML 模板 + **beta / overlay sleeve** 显式化 |
| 风险预算 + 熔断 | **`BookRiskBudget`** + RiskEngine 可选层 + YAML |
| 生产验收 | **`gate_beats_benchmark`** 与研究 PAPER-GO **分列** |

```yaml
# quantflow/config/default.yaml — 默认关闭，产品档可开
risk:
  book_risk_budget:
    enabled: false
    book_gross_limit: 1.2
    book_net_limit: 1.2
    kill_drawdown: 0.15
    beta_sleeve: 1.0
    overlay_sleeve: 0.20
```

---

## 4. 与闭源顶流的差距（仍在）

| 维度 | 本轮 | 仍缺 |
|------|------|------|
| 基准诚实 | ✅ excess 强制 + CLI | 全策略默认挂钩报表 |
| 盈利路径 | ✅ taker 下可 PASS（本窗） | 严格 OOS / 多周期稳健；实盘费率 |
| 风控组织 | ✅ 三层预算 API+装配 | 产品档默认 on；实盘对账 |
| 研究工厂 | 部分 | RD-Agent 真闭环 |
| 数据/算力 | 个人机 | **不追求**万卡 |

---

## 5. 决策（写入项目）

1. **B0 = 研究 OS 基线**，不是赚钱旗舰。  
2. **产品候选** = BTC beta + 低换手 overlay + 账本预算 + **vs-HODL 门**。  
3. **费率必须矩阵披露**（zero / maker_like / taker）。  
4. **T023/T024** 仍是 paper 晋级硬门槛。  

---

## 6. 验收清单（本 goal 迭代）

- [x] 可复现 vs-BTC 超额模块  
- [x] 三层风险预算 + RiskEngine/YAML/TradingSession  
- [x] 真数据评估 + **taker 成本下 PASS（本窗，含扫参边界）**  
- [x] B0 相对失败与 overlay 改进同表披露  
- [x] CLI `eval-btc-overlay`  
- [x] 不宣称幻方硬件/规模 parity  
- [ ] 独立 OOS 合同 + paper 日课 excess 报表（下一迭代）  

---

*向顶流收敛 = 组织原则 + 可度量超额 + 成本诚实；不是文案对齐。*
