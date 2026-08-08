---
title: P0 Baseline Guard 浮动基线机制：数据窗口变化时自动重建
category: testing
createdBy: "harvest:n1-pagination"
sourceRef: maestro-n1-pagination-20260804-20260804-102422
type: knowhow
status: active
---
# P0 Baseline Guard 浮动基线机制

## 适用场景
当回测数据窗口变化（如新增数据）导致回归测试漂移时，需要自动重建基线而非手动调整阈值。

## 机制说明

1. **establish_p0_baseline.py**：在新数据窗口下，运行 4 个策略（trend_following/volatility_breakout/mean_reversion/momentum_rotation）生成参考线
2. **P0 guard 检测**：`test_p0_regression_guard` 对比当前回测结果与基准线，超出阈值标记为漂移
3. **自动重建**：漂移时运行 establish_p0_baseline.py 重新生成基线，4 个测试恢复

## 关键经验
- 数据窗口变化（如追加 2026/04-05 parquet）必然导致基线漂移，属于预期行为
- 基线重建后需确认所有 guard 测试恢复通过
- 与 `.workflow/artifacts/p0-baseline/test-results.json` 配合使用

## 来源
maestro-n1-pagination session (2026-08-04), execution.json INC-1 解决记录