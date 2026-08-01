# Knowhow: QuantFlow 多 Symbol 扩展核心模式

> source: harvest | date: 2026-07-30 | confidence: high
> tags: multi-symbol, TOCTOU, pending-ledger, architecture, concurrency

---

## 1. Pending Exposure 台账三元语义

**模式**: reserve → confirm/partial_confirm → release

```python
# 风控通过后、submit 前冻结
portfolio.reserve(order_id, symbol, notional, strategy_id)

# 完全成交后释放（L4 持仓已由 update_position 更新）
portfolio.confirm(order_id)

# 部分成交：用累积 notional（非 delta_qty × avg_price！）
cum_notional = order.filled_quantity * order.filled_price
portfolio.partial_confirm(order_id, cum_notional)

# 拒绝/超时/撤单后释放
portfolio.release(order_id)
```

**关键陷阱**: `partial_confirm` 参数必须是 `filled_quantity × filled_price`（ccxt 累积契约），不能用 `delta_qty × avg_price`——因为 avg_price 是全局加权均价，乘以增量 qty 不等于真实增量 notional。

**阶段演进**: 内存 dict 是阶段一；阶段二（50+ symbol）替换为 Redis Lua 脚本，接口不变。

---

## 2. 多 Symbol 架构六项决策

| 决策 | 选项 | 核心理由 |
|------|------|----------|
| 扩展模式 | 单进程 asyncio.gather | L4 已天然多 symbol；微服务无收益 |
| TOCTOU | Lock + pending 台账 | Fail-Closed 排除事后校验 |
| on_bar 兼容 | 透明 to_thread 包装 | 接口零变更 |
| 策略实例化 | per-(strategy, symbol) 工厂 | 消除 _bars/_in_position 跨 symbol 污染 |
| 数据获取 | 共享 fetcher + 单 poller | CCXT throttler 全局协调 |
| 50+ 扩展 | 分阶段 Redis | 当前无多机需求 |

---

## 3. Timeout 四象限决策矩阵

超时后 cancel + sync 的 2×2 组合决定 pending 处置：

| | sync ✓ | sync ✗ |
|---|---|---|
| **cancel ✓** | release（象限 A） | release（象限 B，信任 cancel ack） |
| **cancel ✗** | release（象限 C，sync 覆盖真相） | **冻结**（象限 D，Fail-Closed） |

象限 D 兜底: `sweep_stale_pending(max_age_ms=120_000)` 每轮 data loop 执行，超龄强制释放 + CRITICAL alert。

---

## 4. 策略实例跨 Symbol 状态污染

**问题**: TrendFollowingStrategy 持有 `self._bars`、`self._in_position`、EMA 状态等 16 个可变实例属性，完全不区分 symbol。单实例喂多 symbol bar 会导致数据交错（即使串行也坏）。

**解法**: `quantflow/strategy/factory.py` 的 `create_per_symbol()` 为每个 (strategy, symbol) 创建独立实例。单 symbol 时复用原实例（零开销向后兼容）。

---

## 5. CCXT Exchange 实例共享约束

**硬规则**: 全 session 必须共享单个 DataFetcher（单个 ccxt.okx 实例）。CCXT 的 rate-limit throttler 是 per-instance 的；多实例 = 多独立 throttler = 并发直打交易所 → HTTP 429。

---

## 6. sync_positions 返回值契约

`sync_positions() -> bool`：True = L4 已覆盖为交易所真相；False = 查询失败，L4 保留 last-known。调用方据此决定 pending release 策略（四象限矩阵）。

---

## 7. PaperGateway partial_fill_ratio 测试模式

`partial_fill_ratio: float | None`（默认 None = 不启用）。启用后限价单只成交 ratio 比例，返回 PARTIAL 状态。用于测试 partial_confirm 路径——Paper 模式默认永远 FILLED，无法覆盖 partial 分支。
