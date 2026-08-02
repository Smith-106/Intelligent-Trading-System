---
id: kh-order-statemachine-completeness
title: "订单生命周期状态机完整性 — terminal guard + partial modeling"
tags: [state-machine, order, timeout, partial-fill, terminal, order-manager, lifecycle]
source: harvest:20260723-improve-odyssey-trade-main-path
created: 2026-08-01
---

# 订单生命周期状态机完整性

## 问题

OrderManager 的 timeout/partial 状态机残缺，导致：
- timeout 订单不实际撤单，交易所仍挂单
- 迟填充（late fill）覆盖已 timeout 订单，出现"timeout"与"filled"两真相并存
- partial fill 不建模，部分成交时本地仓位簿为零

## 完整性规则

### 1. timeout 必须标记 terminal 状态

```python
# BAD: 只 pop pending dict，不改 status
def check_timeouts(self):
    expired = [oid for oid, o in self._pending.items() if ...]
    for oid in expired:
        self._pending.pop(oid)  # status 仍 SUBMITTED！

# GOOD: 标 terminal + 返回 (id, symbol) 触发撤单
def check_timeouts(self) -> list[tuple[str, str]]:
    expired = [...]
    for oid in expired:
        self._pending.pop(oid)
        self._orders[oid].status = OrderStatus.CANCELLED  # terminal
    return [(oid, self._orders[oid].symbol) for oid in expired]
```

**关键**: check_timeouts 返回值**不可丢弃**——调用方必须用返回的 (id, symbol) 触发实际撤单（`gateway.cancel_order`）。丢弃 = 交易所仍挂单，可迟填充撞死单 id。

### 2. update() 加 terminal-state guard

```python
# BAD: 无 guard，late fill 覆盖 timeout 状态
def update(self, order_id, status, ...):
    self._orders[order_id].status = status  # CANCELLED → FILLED！

# GOOD: 已终态订单拒绝更新
TERMINAL = {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}

def update(self, order_id, status, ...):
    if self._orders[order_id].status in TERMINAL:
        logger.warning(f"late update for terminal order {order_id}")
        return
    self._orders[order_id].status = status
```

### 3. partial fill 必须建模 PARTIAL 状态

```python
# BAD: 直接从 SUBMITTED 跳到 FILLED，丢部分成交
def update(self, order_id, filled_qty, ...):
    if filled_qty >= order.quantity:
        order.status = OrderStatus.FILLED

# GOOD: 建模 PARTIAL 状态
def update(self, order_id, filled_qty, ...):
    order = self._orders[order_id]
    if order.status in TERMINAL:
        return
    if 0 < filled_qty < order.quantity:
        order.status = OrderStatus.PARTIAL  # 部分成交
        # 留 pending，等后续 fill 或 timeout
    elif filled_qty >= order.quantity:
        order.status = OrderStatus.FILLED
```

**关键**: engine.submit 的 FILLED 分支不能跳过 PARTIAL——部分成交时本地仓位簿必须反映已成交部分。

## 完整状态转移图

```
SUBMITTED
  ├── PARTIAL (filled > 0, < quantity)
  │     └── FILLED (fully filled)
  ├── FILLED (fully filled, no partial)
  ├── CANCELLED (timeout / manual cancel)
  ├── REJECTED (gateway reject)
  └── TIMED_OUT → triggers cancel_order → CANCELLED
```

每条转移必须：
1. 更新 `status` 字段
2. 触发对应副作用（撤单 / 仓位更新 / metric）
3. 终态后拒绝后续更新

## 验证方法

状态机遍历测试：对每条合法转移路径，验证：
- status 字段正确更新
- 副作用正确触发
- 终态 guard 拒绝非法更新

## 来源

trade-main-path odyssey (2026-07-23) 根因 C（订单生命周期状态机不完整，3 条 H + 2 C 关联）。修复后 timeout 订单标 CANCELLED terminal + 触发撤单 + PARTIAL 状态建模 + terminal guard，1500 tests 零回归。
