# 验证 Gate 组合放大优化成本

**Source**: ANL-001 性能分析
**Tags**: performance, validation, cpcv

验证管道默认运行 CPCV C(8,2)=28 路径，每条路径可跑 optimize_trials，通过后还跑 rolling 和 anchored 两套 WFO。

以 optimize_trials=50, wfo_windows=5 为例，单次 gate 约 1900 次优化评估（不含 IS/OOS 重算）。优化方向：staged validation modes (smoke/profile/full)、缓存同 (strategy, params, index-range, data-hash) 评估结果、Optuna n_jobs 并行。
