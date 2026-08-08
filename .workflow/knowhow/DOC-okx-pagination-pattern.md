---
title: OKX KLine 分页拉取模式：effective_limit + end 守卫 + MAX_PAGES 保护
category: data
createdBy: "harvest:n1-pagination"
sourceRef: maestro-n1-pagination-20260804-20260804-102422
related:
  - session-maestro-n1-pagination-20260804-20260804-102422
type: knowhow
status: active
---
# OKX KLine 分页拉取模式

## 适用场景
从 OKX 交易所历史 KLine 数据时，需要安全分页、遵守 API 限制、防止无限循环。

## 设计要点

1. **effective_limit = min(limit, 300)**：遵守 OKX 单次最多 300 条限制（即使客户端请求 1000）
2. **end 参数作为唯一终止条件**：当指定 `end_ts` 时，`last_ts >= end_ts` 硬截断退出
3. **无 end 时自然退出**：`len(bars) < effective_limit` 表示数据已拉完
4. **MAX_PAGINATION_PAGES = 500**：硬限制防止 API 异常导致无限循环
5. **去重保护**：相邻页的 bar 通过 timestamp 去重（防止 end 边界重叠）

## 实现参考

```python
# 伪代码模式
effective_limit = min(limit, 300)
pages = 0
all_bars = []
while pages < MAX_PAGINATION_PAGES:
    bars = fetch_kline(symbol, timeframe, limit=effective_limit, after=last_ts)
    if not bars:
        break
    if end_ts and bars[-1].ts >= end_ts:
        bars = [b for b in bars if b.ts < end_ts]
        all_bars.extend(bars)
        break
    all_bars.extend(bars)
    if len(bars) < effective_limit:
        break
    last_ts = bars[-1].ts
    pages += 1
```

## 关键经验
- 测试覆盖：分页拼接、去重、带 end 截断、跨页数据、分页终止、最大页数限制、空 bar 跳过
- 真实验证：45 天 1080 bars 可拉取（远超 300 单页限制）
- P0 guard 需在数据窗口变化时重建基线

## 来源
maestro-n1-pagination session (2026-08-04), review-findings.json R-F3..R-F7