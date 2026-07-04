# 性能优化先恢复 Benchmark 可复现性

**Source**: ANL-001 决策 (Decision 2)
**Tags**: performance, baseline, methodology

优化代码之前必须先确保性能基线可复现。ANL-001 发现 benchmark 因 redis 缺失失败，check_env.py 报缺少 pyarrow/optuna，requirements-lock 与 .venv 不同步。

Wave 1 修复：RedisCache 懒导入 + 安装缺失依赖 + benchmark 通过。

教训：任何性能优化 PR 前必须先确认 benchmark 能在标准环境运行，否则无法量化改进效果。
