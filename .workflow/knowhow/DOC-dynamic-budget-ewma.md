---
title: DynamicBudget EWMA 动态预算缩放：手动 O(n) 递归 + clamp [min_scale,max_scale]
category: strategy
createdBy: "harvest:wave3-s4"
sourceRef: maestro-wave3-s4-20260804-20260804-054608
related:
  - session-maestro-wave3-s4-20260804-20260804-054608
  - knowhow-doc-knowledge-hub
---


# DynamicBudget EWMA 动态预算缩放

## 适用场景
策略预算分配需要根据市场波动率动态调整，同时保持 L4 层 pandas-free 的约束。

## 设计要点

1. **EWMA 波动率缩放**：使用指数加权移动平均计算波动率，缩放预算
2. **手动 O(n) 递归**：不使用 pandas ewm，保持 L4 层 pandas-free
3. **clamp [min_scale, max_scale]**：缩放因子限制在 [min_scale, max_scale] 范围内
4. **空/零标准差历史 → static 回退**：数据不足时使用静态预算
5. **disabled = byte-identical static**：关闭时与静态预算完全一致（33 个现有 budget 测试不受影响）

## 性能特征
- per-signal 成本 O(returns history ≈ 500)
- 无 pandas 依赖（L4 层约束）
- 默认关闭（dynamic_budget.enabled=false）

## 来源
maestro-wave3-s4 session (2026-08-04), review-findings.json R-F1..R-F5