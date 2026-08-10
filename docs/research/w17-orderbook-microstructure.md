# W17 — 盘口微观结构：小步路线（非 HFT）

**Date**: 2026-08-10  
**Source audit**: book-audit + OSS uplift/learnings + smart-search microstructure  
**Related**: [w17-small-team-edge.md](./w17-small-team-edge.md) · [w16-paper-fill-and-strategy-dx.md](./w16-paper-fill-and-strategy-dx.md) · [oss-uplift-pause-bbo-ghost.md](./oss-uplift-pause-bbo-ghost.md)  

---

## 1. 现状一句话

> **Paper 侧 BBO fill / age gate / extra slip 已实现；生产路径没有人调用 `update_orderbook` → 盘口填充实质死代码。**  
> 数据层只有 OHLCV + ticker + funding/OI meta，**无 depth 存储、无 orderbook WS。**

---

## 2. 已有脚手架（勿重复造）

| 能力 | 位置 | 默认 |
|------|------|------|
| `orderbook_fill.enabled` | `PaperGateway` | **false** |
| buy@ask / sell@bid | `_resolve_fill_price` | 仅 enable 时 |
| `extra_slippage` | BBO 路径可选 | 0 |
| `bbo_max_age_sec` | stale → REJECT | 0（关）；overlay 示例 5s |
| `update_orderbook(symbol, bid, ask)` | 写入 `_bbo` + `_bbo_ts` | **无生产 caller** |
| engine 现推送 | `update_market_price(..., close)` | close-only |
| overlay | `paper_orderbook_fill_overlay.yaml` | 文档化 opt-in |
| PauseReasonSet / ghost / preflight disk | OSS uplift | 已落地 |

**Parity 约束（Working Memory）**：paper↔live 共享 ExecutionEngine 抽象；**backtest 是独立向量化路径**。任何 book-aware fill 若声称 backtest 覆盖，必须在 `BacktestEngine` 另有等价实现，或 **明确排除 backtest**。

---

## 3. 行业对照（学什么 / 不学什么）

| 来源 | 可学 | 不学 |
|------|------|------|
| binance-deribit-btc | market_ready（book/mark age）、pause set、ghost | 跨所期权、Mixin 巨石、扫簿套利主产品 |
| Nautilus / Hummingbot（本地对照仓） | book delta 概念、深度结构 | Rust/C++ 核、队列位置、强制 live book |
| Retail limit order 研究 (2024–25) | 限价/耐心流动性降成本 | 美股零售监管细节整套 |
| Spencer Logic 零售 algo 基建 | 浅簿冲击、风险叠加可见 | 对 broker 的 sub-ms SLA |
| QuantumFlow 类 HFT 样板 | 监控分层、成本项清单 | 主产品改为 HFT 预测引擎 |

---

## 4. 小步路线图（P0→P3）

### Step 0 — 已完成（W16 + OSS uplift）

- [x] Opt-in BBO fill 模型  
- [x] Age gate 字段与 reject  
- [x] 测试覆盖 gateway 行为  
- [x] 文档声明“不自动拉 OKX book”

### Step 1 — **BBO Feed（唯一阻塞，W18 首选运维刀）**

**目标**：让 `update_orderbook` 在 paper session 有真实调用方。

最小实现（推荐顺序）：

1. **Ticker bid/ask**（CCXT `fetch_ticker` / 已有 watch 扩展）→ 每 bar 或独立 poll 推送  
2. 经 `ExecutionEngine` 或 session hook → `PaperGateway.update_orderbook`  
3. 保持 `orderbook_fill.enabled` 默认 false；文档 + overlay 开启  
4. 单测：mock ticker → fill 价 = ask/bid；无 BBO + age>0 → reject  

可选下一步：`fetch_order_book` limit=1/5 替代 ticker（仍非全深度）。

**非目标**：WS 全深度落盘、L2 重建、回放历史 book（无历史则不做假装）。

### Step 2 — 门禁产品化

- age gate 与 `PauseReasonSet` / KillSwitch 对齐文案（`bbo_stale` reason）  
- funding **risk gate**（过高拒开仓）复用 `MarketMetaFetcher` freshness — **非 alpha**  
- preflight：若 overlay 开启 orderbook_fill，检查 feed 任务是否配置  

### Step 3 — Depth-lite（可选）

- top-N notional 估算简单 impact 或 partial fill 比例  
- 仅 paper；参数 YAML；默认关  
- **不做**：queue position、cancel/replace 博弈、延迟分布拟合  

### Step 4 — 研究扩展（有数据再做）

- CVD / trade aggressor（需 trades）  
- 盘口不平衡特征进 FeatureStore（严格 PIT：仅用决策 ts 前快照）  
- 历史 book 回放合同（成本高，单独立项）  

---

## 5. 与策略 / 回测的接口契约

| 路径 | Book fill | 说明 |
|------|-----------|------|
| paper + overlay on + feed | ✅ | 目标态 |
| paper 默认 | close/last + flat slip | B0 稳定 |
| live | 真实成交；age gate 可共用思想 | 不在 W17 验收 |
| vectorized backtest | ❌ 默认 | 除非显式模型 + 新合同 |
| paper_replay 晋级 | 须在 run_meta 记录 `orderbook_fill` 与 feed 指纹 | W14 精神 |

---

## 6. 风险与失败模式

| 失败 | 后果 | 缓解 |
|------|------|------|
| 开启 fill 但无 feed | 全拒单或静默回退 last | age>0 拒单；日志 metric |
| 交叉盘 / 脏 BBO | 错误 fill | `update_orderbook` 已 ignore invalid |
| 把 ticker mid 当 last 乱写 | 策略状态漂 | `mid_to_last` 默认策略保持现状并测 |
| 回测声称 book 保真 | 晋级虚假 | W14 拒绝非 paper 路径；文档排除 |

---

## 7. 验收口径（Step 1 实现时）

- 默认配置下 B0 / 既有 paper 测试 **byte-stable**。  
- overlay 开启 + mock BBO：买单成交价=ask（±extra_slip）。  
- stale BBO：`bbo_max_age_sec=5` 拒单。  
- 无 Nautilus 依赖；无 Redis 强依赖。  
- run_meta 可记录 `orderbook_fill_enabled` / `bbo_source`.  

---

## 8. 决策摘要

| 问题 | 答案 |
|------|------|
| 要不要上全深度 HFT？ | **不要** |
| 下一刀是什么？ | **BBO feed 接线**，不是再写 fill 公式 |
| 盘口是 alpha 还是保真？ | **先保真与门禁**；alpha 另立合同 |
| 和波浪关系？ | 正交；波浪管结构，盘口管成交假设 |

---

*Research only. No code changed in W17.*
