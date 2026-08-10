# W17 — 小团队如何接近行业领先（研究总纲）

**Date**: 2026-08-10  
**Mode**: research-only（本波 **无代码变更**）  
**Parent**: [option-b-evolution-roadmap.md](./option-b-evolution-roadmap.md) · [architecture-diagnosis-vs-oss.md](./architecture-diagnosis-vs-oss.md)  
**Method**: teammate 三审计（wave / book / factor）+ smart-search 深度证据 + 本地 OSS 对照仓  
**Product boundary**: 不换引擎；不引入跨所/期权/Rust/HFT 队列；B0 默认行为 byte-stable；paper-first  

---

## 1. 北极星（重申）

小团队的“接近行业领先”**不是** win_rate 或更花的因子，而是：

> **成本后可复现的 paper-first 研究 OS**  
> 晋级数字权威路径 = paper_replay / TradingSession 事件路径（W14）  
> VectorBT / BacktestEngine 仅筛选，不得单独 GO  

外部证据与此同向：零售侧更现实的优势来自 **稳健组合 + 可运维执行**，而不是单策略“最锋利刀”（Medium / JIN System Architect, 2026-04）。系统化机构侧强调 **数据纪律、执行保真、风险可见**（HedgeNordic Systematic Strategies, 2024-05）。

---

## 2. 我们已有的行业级地基（不要推倒重来）

| 能力 | 状态 | 证据 |
|------|------|------|
| 六层 + Protocol + YAML | 稳定 | AGENTS.md / architecture |
| 防过拟合门（CPCV/DSR/PBO/WFO） | Phase 2 ✅ | validation 管道 |
| 成本 fidelity + fee×slip 网格 | ✅ | T001/T002/W14 |
| FeatureStore PIT 截止查询 | 基本 ✅ | `feature_store.compute_features` end=timestamp |
| Paper BBO fill + age gate | 脚手架 ✅，**无 feed** | W16 + OSS uplift |
| PauseReasonSet / Ghost / Preflight disk | ✅ | OSS uplift `487be3b` |
| Funding/OI meta + freshness | 成熟 | `MarketMetaFetcher` |
| Elliott 规则栈（铁律/通道/Fib） | research-grade，有缺口 | wave-audit |
| 21 经典 + 5 休眠因子 + 6 wave 名 | 双轨不一致 | factor-audit |

**结论**：差距不在“缺一个超级引擎”，而在 **若干可测的保真与暴露缺口**。

---

## 3. 外部证据（smart-search，已 gap_check=closed）

| 主题 | 可迁移主张 | 来源 | 对本仓含义 |
|------|------------|------|------------|
| 零售量化现实 | 组合“够好”策略 + 避开不匹配的花哨系统 | [Medium: realistic retail quant](https://medium.com/jin-system-architect/the-most-realistic-quant-system-for-retail-traders-isnt-the-sharpest-knife-it-s-the-one-that-826da1071acc) | 继续 B0 合同纪律；波浪/盘口作 **闸门/辅助**，非主 alpha 神话 |
| Look-ahead | 未来信息进训练/信号 → 纸面超额、实盘崩 | [Medium: look-ahead bias](https://medium.com/funny-ai-quant/look-ahead-bias-in-quantitative-finance-the-silent-killer-of-trading-strategies-bbbbb31d943a) | 强化 zigzag/wave 确认契约 + FeatureStore 写路径 + 测试 |
| 零售限价/盘口 | 限价与耐心流动性可降成本；顶档/深度影响 fill | [Retail Limit Orders PDF](https://microstructure.exchange/papers/Retail%20Limit%20Orders%2004082025.pdf) | paper 先 BBO 买卖价 fill；深度仅 lite 影响，不做队列 |
| 零售 algo 基建 | 延迟/浅簿/风险叠加是真问题 | [Spencer Logic 2025](https://www.spencerlogic.com/blog/rise-of-the-retail-algo-trader-reinventing-broker-infrastructure-for-2025) | 个人系统做 **age gate + reject**，不追 sub-ms |
| 系统化产业 | 数据过载下纪律与流程 > 单点创新 | [HedgeNordic 2024](https://hedgenordic.com/wp-content/uploads/2024/06/Systematic-Strategies-2024.pdf) | 合同/WFO/日课 streak 优先于新因子堆砌 |
| HFT 盘口 ML 样板 | 完整 book→特征→live 栈存在，但属另一产品 | [QuantumFlow HFT engine](https://github.com/mohin-io/QuantumFlow---Next-Generation-HFT-Prediction-Engine) | **对照边界**：可学分层监控，**不抄** HFT 主产品 |

> 证据目录（本机）：`%TEMP%/smart-search-evidence/20260810-1218-retail-quant-trading-small-team-best-practices-2/`

---

## 4. 四条研究结论（分册）

| 分册 | 一句话 | 文档 |
|------|--------|------|
| 波浪 | 规则栈够用；最大风险是 **repaint + pivot 价格失真 + on_bar 空实现** | [w17-wave-repaint-boundary.md](./w17-wave-repaint-boundary.md) |
| 防未来 + 因子 | PIT 调用侧正确；缺口在 **写回覆盖、wave 通道全序列、休眠因子接线、引擎“27”口径** | [w17-antifuture-and-factors.md](./w17-antifuture-and-factors.md) |
| 盘口 | Fill 模型已写好；**唯一阻塞是 BBO 推送路径** | [w17-orderbook-microstructure.md](./w17-orderbook-microstructure.md) |
| 总纲（本文） | 小团队路线 = 保真 > 新 alpha；P0–P3 排序 | 本文 §5 |

---

## 5. P0–P3 候选小改进（W18+ 候选，**不自动开工**）

### P0 — 正确性 / 防自欺（优先）

| ID | 项 | 为何 | 默认安全 |
|----|----|------|----------|
| W18-P0a | ZigZag 携带真实 high/low pivot 价；策略停用 close 替代 | 振幅/回撤/Fib 全部失真 | 行为变更需 golden；默认新 API / flag |
| W18-P0b | PROGRESSIVE 仅在 **已确认 pivot** 上发信号（末位 in-progress 不交易） | repaint → 纸面虚高 | 默认更严；可 YAML 放宽 |
| W18-P0c | low-consensus fallback **显式化**（flag/skip，禁止静默降级） | ISS-20260613-007 缺口 | fail-closed 更安全 |
| W18-P0d | FeatureStore `save_features` 防“后写覆盖同 timestamp”或审计 | 写路径可污染 PIT | 默认 keep-first 或 version |

### P1 — 接线与暴露（高杠杆、低架构风险）

| ID | 项 | 为何 | 默认安全 |
|----|----|------|----------|
| W18-P1a | Engine 推送 BBO（ticker bid/ask 或 `fetch_order_book` top）→ `PaperGateway.update_orderbook` | 解锁 W16 fill 死代码 | overlay 默认关 |
| W18-P1b | 暴露休眠因子：supertrend / keltner / donchian / dema / stochRSI → `FACTOR_NAMES`+`batch`/`compute_all` | 已实现未接线 | 纯加法 |
| W18-P1c | `WaveInvalidationChecker` + enrich 接入 liu_yudong 路径 | 已测未接线 | 策略级 opt-in |
| W18-P1d | 修正 RSI 背离参考点（W1 极值非 origin） | divergence 候选 bug | 单测锁 |

### P2 — 研究纪律与 DX

| ID | 项 | 为何 |
|----|----|------|
| W18-P2a | 文档/列表口径：FactorRegistry=6 wave；Engine 经典=21；休眠=5；勿再写“27 registered” | 防知识腐烂 |
| W18-P2b | wave_channel 全 band 序列标注 research-only；下游只消费 `w5_target` | 防误用 lookahead 带 |
| W18-P2c | Elliott 真实数据 WFO 烟测（替代纯 synthetic 验收叙事） | 现 backtest 仅 synthetic |
| W18-P2d | 模板 `ElliottWaveStrategy` 弃用或修 SHORT TP 不一致 | toy 轨污染 |

### P3 — 可选增强（明确非目标优先）

| ID | 项 | 非目标 |
|----|----|--------|
| W18-P3a | top-N depth → 简单 impact/partial 尺寸（非队列） | 不做 queue position / latency model |
| W18-P3b | CVD 代理 / session VWAP / CMF（需 tick 或 agg trade） | 无数据则不做 |
| W18-P3c | Ichimoku / CCI 等 mainstream 补齐 | 仅在有合同需求时 |
| W18-P3d | funding 作 **risk gate**（非 alpha）接 KillSwitch/pause | 不改 B3 阈值 |

---

## 6. 明确不做（W17 冻结）

- 换 Nautilus / Freqtrade / Lean / 自研 Rust 核  
- 跨所、期权合成、Mixin 巨石  
- 强制 Redis、强制 live book  
- 静默改 B0 slip/fill/阈值（新合同 B4+）  
- 把 HFT orderbook ML 当主产品叙事  
- 用 VectorBT 数字晋级  

---

## 7. 小团队作战原则（可执行）

1. **一条权威路径**：paper_replay / on_bar 事件路径出数字。  
2. **先修失真，再堆因子**：pivot 价 / repaint / BBO feed 优先于 Ichimoku。  
3. **加法默认关**：overlay + YAML；B0 byte-stable。  
4. **双轨合并或弃用**：research-grade `liu_yudong_wave` vs toy `templates/elliott_wave` 二选一主路径。  
5. **证据 > 故事**：每个新因子/盘口特性配合同 + fingerprint + 测试。  
6. **运维门禁继续偷师**：PauseReason / BBO age / ghost / preflight（已做），下一刀是 **feed + risk gate**。  

---

## 8. 建议下一步（人工裁决）

| 选项 | 内容 | 何时 |
|------|------|------|
| **W18a（推荐）** | P0a–P0c 波浪保真包（pivot 价 + 确认 pivot + consensus flag） | 想先修研究自欺 |
| **W18b** | P1a BBO feed 最小接线（ticker bid/ask） | 想激活 W16 paper 保真 |
| **W18c** | P1b 休眠因子暴露 + 口径文档 | 低风险 DX |
| **并行** | T023 墙钟至 consecutive≥7 | 不依赖 W18 |

---

## 9. 审计来源

| 审计 | 范围 | 结论消费于 |
|------|------|------------|
| wave-audit | `quantflow/indicators/{zigzag,wave_*,fibonacci,divergence,critical_level,elliott_wave}.py` + strategy/signal | 波浪分册 |
| book-audit | `paper_gateway` / data fetcher / market_meta / OSS notes | 盘口分册 |
| factor-audit | `IndicatorEngine` / FactorRegistry / FeatureStore / dormant funcs | 因子分册 |
| smart-search | 6 sources, gap_check closed | §3 |
| OSS | binance-deribit-btc learnings + uplift | P1 运维连续性 |

---

*W17 research complete when this file + three satellite docs exist and roadmap §W17 is marked. Implementation requires explicit W18+ session.*
