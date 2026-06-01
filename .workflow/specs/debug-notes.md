---
title: "Debug Notes"
readMode: optional
priority: medium
category: debug
keywords:
  - debug
  - issue
  - workaround
  - root-cause
  - gotcha
---

# Debug Notes

<spec-entry category="debug" keywords="调试,日志,事件总线,异常,kill-switch" date="2026-05-29">
### 调试策略与日志规范
使用 structlog 结构化日志，关键事件（下单、撤单、风控触发）写审计日志。EventBus 发布事件时捕获 handler 异常，不阻塞其他 handler。KillSwitch 是最终安全网——所有风控失败且无法恢复时应触发 KillSwitch 而非忽略错误。
</spec-entry>

<spec-entry category="debug" keywords="VectorBTEngine,BacktestEngine,重命名,import-error" date="2026-06-02">
### VectorBTEngine → BacktestEngine 重命名
`backtest.py` 中的 `VectorBTEngine` 已重命名为 `BacktestEngine`（纯 pandas/numpy 实现，不依赖 VectorBT）。所有引用（`__init__.py`、`optimizer.py`、`cli/main.py`、`validation/cpcv.py`、`validation/pbo.py`、`validation/wfo.py`、`tests/unit/test_backtest.py`）已同步更新。若新建代码引用 `VectorBTEngine`，将导致 ImportError。
</spec-entry>
