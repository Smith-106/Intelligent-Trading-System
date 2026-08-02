---
id: kh-failclosed-gateway-contract
title: "Fail-Closed 网关安全契约 — 防紧急制动假报成功"
tags: [fail-closed, gateway, idempotency, reduceOnly, wait_for, security, kill-switch]
source: harvest:20260723-improve-odyssey-trade-main-path
created: 2026-08-01
---

# Fail-Closed 网关安全契约

## 问题

交易网关的 query/read 方法在异常时返回 `[]` / `False` / `None`，与合法 empty 返回不可区分。这导致 KillSwitch 等紧急路径在查询失败时假报"无仓可平"成功，真实仓位仍敞口——紧急制动形同虚设。

## 契约规则

### 1. 禁止 fail-silent 返回

```python
# BAD: 查询失败静默返回空
async def query_positions(self) -> list[Position]:
    try:
        return await self._exchange.fetch_positions(...)
    except Exception:
        logger.critical("query failed")
        return []  # ← 与"无仓位"不可区分！

# GOOD: typed exception, 调用方显式处理
async def query_positions(self) -> list[Position]:
    try:
        return await asyncio.wait_for(
            self._exchange.fetch_positions(...),
            timeout=self.CALL_TIMEOUT
        )
    except Exception as e:
        raise GatewayError(f"query_positions failed: {e}") from e
```

### 2. CCXT 调用必须包 asyncio.wait_for

所有 CCXT exchange 调用（create_order / cancel_order / fetch_positions / fetch_ohlcv 等）必须有 per-call timeout，防止 TCP stall 无界挂起。

```python
CALL_TIMEOUT = 10.0  # 网关操作
DATA_TIMEOUT = 30.0  # 数据层操作

result = await asyncio.wait_for(
    self._exchange.create_order(...),
    timeout=self.CALL_TIMEOUT
)
```

### 3. 实盘下单注入 clientOrderId 幂等键

超时重试时若无幂等键，交易所可能产生重复实盘订单（双发）。

```python
order = Order(
    ...
    client_order_id=f"{strategy_id}-{symbol}-{timestamp_ms}",  # 幂等键
)
```

### 4. 平仓 Order 设 reduceOnly

实盘合约模式下，stale 仓位查询可能把"平仓"变成"反向开仓"。

```python
close_order = Order(
    symbol=symbol,
    side=Side.SELL if position.quantity > 0 else Side.BUY,
    quantity=abs(position.quantity),
    reduce_only=True,  # ← 防止反向开仓
)
```

## 验证方法

审计网关方法的四重检查：

1. **error path** 是否复用 empty-result 值（`[]` / `False` / `None`）？→ 必须 raise typed exception
2. **CCXT 调用** 是否有 timeout floor（asyncio.wait_for）？→ 无 timeout = 无限阻塞风险
3. **下单** 是否有幂等键（clientOrderId）？→ 无幂等 = 超时重试双发
4. **平仓** 是否有 reduceOnly？→ 无 reduceOnly = stale 仓位可变反向开仓

## 来源

trade-main-path odyssey (2026-07-23) 的 69 findings 审计中，根因 A（网关 fail-silent，5 条 C/H）和根因 B（KillSwitch 三重缺位，3 条 H）收敛出的安全契约。修复后 execution 层全部从 fail-silent 迁移到 GatewayError typed exception，1500 tests 零回归。
