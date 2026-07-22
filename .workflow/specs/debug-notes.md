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

<spec-entry category="debug" keywords="e712,ruff,autofix,pandas,numpy,bool" date="2026-07-05" title="E712 on pandas/numpy bools: use bool(x), never accept the `is True` autofix" description="ruff E712 unsafe autofix rewrites ==True to is True, which is False for np.bool_ — silently weakens assertions">
### E712 on pandas/numpy bools: use bool(x), never accept the `is True` autofix

ruff E712 flags `x == True`. Its **unsafe** autofix rewrites to `x is True`. For `numpy.bool_` / pandas scalars, `np.bool_(True) is True` evaluates to `False` (identity comparison against the singleton `True`), so the autofix **silently weakens the assertion** — the test starts passing for the wrong reason, or passes when it should fail.

Fix: for each E712 hit on a pandas/numpy scalar, replace `assert x == True` with `assert bool(x)` (and `== False` → `assert not bool(x)`). Never accept the `is True` / `is False` autofix on data-adjacent code without a manual check.

Why the obvious fix fails: `is True` is the lint-tool's suggested rewrite and looks correct, but identity comparison against the singleton `True` is `False` for numpy bools — a subtle semantic break that tests won't catch (they pass either way).

Detection: review every E712 hit in `tests/unit/test_*.py` that touches pandas DataFrames / numpy arrays / `.iloc` / `.loc` before accepting autofix.

Source: odyssey-debug ci-ruff-breakage session (P2, manual fix in test_runtime_extra.py).
</spec-entry>

<spec-entry category="debug" keywords="yaml,pydantic,schema-drift,config-dropped,silently-ignored" date="2026-07-05" title="YAML key without a matching pydantic field is silently dropped at load time" description="A default.yaml key with no model field is decorative; consumer hardcodes the same default so tests pass — config changes have zero effect">
### YAML key without a matching pydantic field is silently dropped at load time

A `default.yaml` key with no matching `RiskConfig`/`ExecutionConfig`/`AppConfig` pydantic field is silently dropped at load time. The consumer hardcodes the same default, so tests pass — but the YAML is decorative. An operator tuning that value sees **zero** change.

Recurring instances: `risk.kelly_fraction` (fixed), `risk.var_confidence` (fixed), `risk.position_limit_pct * 100` units bug (the clamp was a no-op for the entire project lifetime because of a separate `*100` units defect). Same class of bug.

Fix template: (1) add the field to the pydantic model with the same default as the YAML; (2) consume it from `self._config.*` instead of a hardcoded literal (config is the single source of truth — never hardcode a literal that duplicates a YAML default); (3) add a schema-drift guard test.

Durable guard: `tests/unit/test_config.py::TestConfigSchemaDrift::test_default_yaml_has_no_dropped_keys` walks `default.yaml` vs `AppConfig` and fails on any scalar key without a matching model field. This locks the `kelly_fraction`/`var_confidence` class of bug from recurring.

Source: odyssey-debug position-sizing-regression session (L1) + odyssey-review deepfix session (Pattern 4, I15).
</spec-entry>
