---
title: 交易引擎恢复链架构：reset → restore → _verify_recovery
category: architecture
createdBy: "harvest:wave1-precheck"
sourceRef: maestro-wave1-precheck-20260803-20260803-075540
type: knowhow
status: active
related:
  - DOC-exchange-health-breaker
  - DOC-state-store-atomic-write
---
# 交易引擎恢复链架构

## 适用场景
交易引擎启动时，需要从检查点恢复状态，验证恢复完整性，并确保不完整恢复不导致错误交易。

## 恢复链顺序

1. **reset()**：重置运行时状态到干净初始态
2. **restore()**：从检查点加载持久化状态
3. **_verify_recovery()**：验证恢复状态的完整性

## 安全设计
- **recovery_unverified 状态**：恢复后若验证未通过，阻止新开仓，只允许 FLAT（平仓）操作
- **corrupt checkpoint fail-closed**：损坏的检查点返回失败，不尝试部分恢复
- **_periodic_maintenance 故障隔离**：维护操作的失败不影响主交易循环

## 关键经验
- 恢复链顺序不可颠倒（必须先 reset 清除旧状态再 restore）
- 恢复验证失败时，系统应保持"可平仓不可开仓"的安全状态
- 冷启动（无检查点）时 fail-closed 到默认配置

## 来源
maestro-wave1-precheck session (2026-08-03), strategy/engine.py recovery chain