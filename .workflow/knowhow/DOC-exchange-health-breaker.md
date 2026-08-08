---
title: ExchangeHealthMonitor 滞后断路器设计模式
category: architecture
createdBy: "harvest:wave1-precheck"
sourceRef: maestro-wave1-precheck-20260803-20260803-075540
type: knowhow
status: active
related:
  - DOC-engine-recovery-chain
  - DOC-monitoring-sink-protocol
---
# ExchangeHealthMonitor 滞后断路器设计模式

## 适用场景
交易所 API 连接可能出现间歇性故障，需要一个断路器防止短时间内反复触发/恢复，同时保证故障时快速熔断。

## 设计要点

1. **触发条件**：window error-rate > 0.5 OR 50011 streak >= 3 触发跳闸
2. **open-state 行为**：open-state failures 重新锚定冷却时间，防止冷却期间高频失败导致无限循环
3. **half-open 恢复**：需要 3 次连续成功才关闭断路器
4. **窗口清理**：`_close_circuit()` 清除窗口数据，防止立即重跳闸

## 状态机

```
CLOSED ──(error-rate > 0.5 OR 50011 streak >= 3)──→ OPEN
  ↑                                                   │
  │  (3 consecutive successes)                        │  (failures re-anchor cooldown)
  │                                                   ↓
  └─────── HALF_OPEN ←──── (cooldown expires) ────────┘
```

## 安全属性
- **fail-closed to trading**：断路器打开时，RiskEngine 拒绝所有新开仓（incl. FLAT 可能被拒绝）
- **fail-closed to exposure**：交易所暴露度检查仅拒绝 LONG 新开仓（允许平仓降低风险）
- **duck-typed injection**：通过构造函数注入，保持 L4→L5 分层

## 来源
maestro-wave1-precheck session (2026-08-03), exchange_health.py correctness spotcheck