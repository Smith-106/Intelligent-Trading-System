# 架构诊断：胜率焦虑 vs 是否大改架构

**Date**: 2026-08-10  
**Method**: OSS 对照（`Desktop/oss-quant-benchmark`）+ QuantFlow 合同/门控证据 + 双 agent 深潜（explorer OSS map + analyst QF diag）  
**Note**: `team-swarm` ACO 总线在本 Pi 环境不完整；以 teammate 并行探索替代蚁群迭代。

**B0 硬数（gate.json）**: decision=**PAPER-GO** · OOS meanSh **0.727** · cumRet **+12.93%** · maxDD **2.55%** · full_orders 1547。

---

## 0. 一句话结论

| 问题 | 结论 |
|------|------|
| **胜率不高 ⇒ 架构坏了？** | **否。** 项目北极星明确 **不是 win_rate**；B0 在成本后 WFO 上 **PAPER-GO**，说明六层 + paper 路径能交付可复现研究 OS。 |
| **B1–B3 未升级 ⇒ 引擎废了？** | **否。** 负结果是 **信号族 / 数据稀疏 / 升级条** 证据，不是 L5 Gateway 崩坏。 |
| **要不要大改架构（换 Nautilus/Freqtrade/Lean）？** | **不建议。** 大改解决不了 alpha/数据问题，且违反 paper-first、OKX 个人闭环、非 HFT 边界。 |
| **要不要改？** | **要做针对性增强（B）**，不是推倒重来（C）。 |

推荐选项：
- **默认 (A)**：不重写六层；继续日课 + 新信号/数据合同（analyst 主推）。  
- **可选 (B)**：定向演进（paper 保真 / meta 数据 / 晋级纪律）— 若要“动刀”只动这些。  
- **拒绝 (C)**：大换 Nautilus/Freqtrade/Lean 引擎。

---

## 1. 当前 QuantFlow 架构（事实）

```
L1 data → L2 indicators → L3 strategy/research/validation
        → L4 signal/risk → L5 execution → L6 monitoring
```

| 原则 | 状态 |
|------|------|
| 层间单向依赖 | 设计在位 |
| 接口 + YAML | 在位 |
| EventBus 解耦 | 在位 |
| paper-first 门控 | cost_fidelity / funding_tca / paper_readiness **fail-closed** |
| B0 | **PAPER-GO**（OOS meanSh≈0.73，cum≈+13%，checks 全过） |
| B1–B3 | **FROZEN KEEP B0**（合法负结果） |

**已知结构缝（不是“整架构错误”）**：

1. **双路径**：`BacktestEngine`（向量化）vs `paper_replay`/`TradingSession`（事件路径）— parity 文档已写明 paper↔live 对齐，backtest 不共享账本。  
2. **Meta 数据**：funding/OI 覆盖远短于 OHLCV pin → B3 **0 成交**（阈值 + 稀疏）。  
3. **研究吞吐**：VectorBT/Optuna 与事件 replay 未完全同一套 bar 语义。

这些是 **演进点**，不是“必须换框架”的证据。

---

## 2. OSS 对照（`oss-quant-benchmark`）

| 项目 | 角色 | 架构风格 | 与 QuantFlow 关系 |
|------|------|----------|-------------------|
| **freqtrade** | 全能 CEX bot | 策略插件 + dry-run + hyperopt + 多所 | 产品化 bot 强；**多所/UI/hyperopt 是范围膨胀** |
| **jesse** | 研究优先 crypto | 简洁策略 DSL、多 TF、自托管 | **最接近** research-first；可借鉴策略 API 清晰度 |
| **nautilus_trader** | 生产事件引擎 | Rust 核 + Python 控制面，研究=仿真=live | **理想 parity**；迁移成本极高，偏机构/HFT 气质 |
| **qlib** | AI 研究平台 | 因子/模型流水线、RD-Agent | **研究层可借鉴**；已在 AGENTS 规划 AI(V3) |
| **hummingbot** | MM / 多场所 | 高频做市、CEX+DEX | **非目标**（HFT/多所超市） |
| **vnpy / Lean / FinRL / OctoBot** | 多市场 / 多资产 / RL / UI bot | 各有生态 | 对个人 OKX paper OS **投入产出差** |

### 可借鉴（不整仓替换）— explorer 深潜摘要

1. **One engine, two reality sources**：paper/live 共用执行核，仅 gateway+clock 不同；backtest 可保持向量化旁路（与 QuantFlow「parity=paper↔live」一致；nautilus/hummingbot/freqtrade 均未宣称 backtest=live 字节级）。  
2. **Paper 吃真盘口**（hummingbot `simulate_buy/sell`、freqtrade dry-run orderbook）— 提高 dry-run 保真，**仍非 HFT**。  
3. **成本可注入组件**（nautilus Fee/Fill/LatencyModel；qlib open/close cost）— 与现有 fee×slip + funding_tca 同方向。  
4. **晋级前显著性门**（jesse bootstrap / Monte-Carlo shuffle；freqtrade lookahead-analysis）— 叠在 CPCV/DSR/PBO/WFO 上，不换引擎。  
5. **Jesse DX + Qlib 研究旁路**：策略 API 更薄；RD-Agent 只进 validation，不直连 live。

### 明确不要抄

| 模式 | 原因 |
|------|------|
| 多交易所超市 | 非目标 |
| Hyperopt 当晋级主路径 | 已禁 Optuna 晋级 |
| MM/HFT 微结构主线 | 非 paper-first 研究 OS |
| 为抬 win_rate 放宽 fee/funding 门 | 违反北极星 |
| 整仓迁 Lean/Nautilus | 重写 1–2 年，alpha 问题仍在 |

---

## 3. 「胜率不高」根因矩阵

> 项目文档：`win_rate` **不进 done_when**；优化的是 **成本后稳健期望**。

| 症状 | 更可能层 | 证据 | 要大改架构？ |
|------|----------|------|--------------|
| 主观“胜率低” | **KPI 错配** | 北极星非 win_rate；B0 GO 看 OOS Sharpe/DD/订单 | 否 |
| B1/B2 未超 classic | **信号/结构** | Wave-C / 合同 KEEP；classic 仍优 | 否 |
| B3 0 单 | **数据 + 阈值** | max\|funding\|=0.0005 &lt; 0.001；窗 NARROWED | 否（先补 meta） |
| 成本后收益变差 | **市场 + TCA** | fee×slip grid 暴露 drag；属正确行为 | 否 |
| 回测好看 paper 差 | **双路径 / 成本未对齐** | 已知 Backtest vs Session 分裂 | **小改路径统一**，非换框架 |
| 样本不足 promote 拒 | **运营墙钟** | T023 3/7；T016 fail-closed | 否 |

**架构“大问题”不成立的核心证据**：若 L4/L5/事件总线整体错误，B0 **无法**在多标的 shared-RP + 0.1% 成本 + WFO 上给出 PAPER-GO。负挑战者说明 **筛选在工作**。

---

## 4. 大改（C）会带来什么

| 动作 | 成本 | 对胜率/Sharpe |
|------|------|----------------|
| 换 Nautilus/Lean 为核 | 极高 | **不自动提高** alpha |
| 变 Freqtrade 多所 bot | 高 + 范围漂移 | 可能更差的研究纪律 |
| 拆掉 fail-closed 成本门 | 低（但错误） | 纸面胜率↑、实盘期望↓ |
| 重写六层为“更潮”的图 | 高 | 无合同证据支持 |

**结论**：大改是 **情绪解法**，不是证据解法。

---

## 5. 建议：定向演进（B）— 架构“小手术”

按优先级（不破坏 B0 / 门控）：

### P0 — 研究主路径收敛（架构缝）

1. **以 `TradingSession` / `paper_replay` 为唯一晋级路径**；VectorBT 仅作筛选，晋级合同强制事件路径数字。  
2. 文档/CI：任何 “GO” 必须附 **paper_replay 指纹**，禁止纯向量化海报。  
3. （可选）逐步让 BacktestEngine 输出 **对齐字段**，但不要求一夜合并代码库。

### P1 — 数据与信号（真正影响表现）

1. **密集 funding/OI 历史** → 再跑 B3（新 `run_meta`，禁覆盖）。  
2. 扩展 admitted 后 **新信号合同**（横截面/funding 修正阈值），不是换引擎。  
3. Feature Store 时间点安全 + 与 on_bar 特征一致（已有方向，加深）。

### P2 — 执行保真（仍非 HFT）

1. 保持 paper overlay 成本；funding_tca 继续挂在 GO 叙事。  
2. checkpoint/recon 维持 **默认关** + 可选 overlay（T029）。  
3. 不做多所、不做 Rust 内核，除非未来有明确 latency 合同（目前没有）。

### P3 — 研究 OS 体验

1. Jesse 式策略模板 DX（更少样板代码）。  
2. Qlib/RD-Agent **旁路**因子挖掘，产出进 validation 门，不直连 live。

---

## 6. 决策表（给你勾）

| 选项 | 含义 | 建议 |
|------|------|------|
| **A. 不改架构** | 只跑日课 + 新信号合同 | 可作默认 |
| **B. 定向演进** | P0–P2 上表 | **推荐** |
| **C. 大改/换引擎** | Nautilus/Freqtrade/Lean 重写 | **不推荐**（无证据） |

若坚持 C，需先回答：

1. 要解决的 **可测** 故障是什么（不是“胜率观感”）？  
2. 迁移后 90 天内如何 **复现 B0 PAPER-GO**？  
3. 是否接受 6–18 个月无新 GO？

答不上来 → 不做 C。

---

## 7. 与当前残留的关系

| 残留 | 与架构 |
|------|--------|
| T023 墙钟 3/7 | **运营**，非架构 |
| 真实 promote 证据 | **样本**，非架构 |
| 人审 OSS C | **治理**，非架构 |
| 胜率焦虑 | **KPI**；请改看 OOS Sharpe / 成本后期望 / 合同 GO |

---

## 8. 建议的下一波（若立项）

**已选 B** → 见 [option-b-evolution-roadmap.md](./option-b-evolution-roadmap.md)

```text
W14  研究路径纪律：晋级仅 paper_replay + 指纹  ✅ 已交付（promotion_path）
W15  Meta 数据充实 + B3/B4 合同（非换皮 B1）
W16  策略 DX + Feature 一致性审计
（明确不做）引擎大换血 / 多所 / 为 win_rate 松门
```

---

*Architecture is not the bottleneck for “win rate”; evaluation protocol and alpha/data are. Keep the six-layer OS; evolve the research path and data plane.*
