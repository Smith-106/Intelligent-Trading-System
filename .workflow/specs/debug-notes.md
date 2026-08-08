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

<spec-entry category="debug" keywords="调试,日志,事件总线,异常,kill-switch" date="2026-05-29" sid="S-legacy-a38f0ecb">
### 调试策略与日志规范
使用 structlog 结构化日志，关键事件（下单、撤单、风控触发）写审计日志。EventBus 发布事件时捕获 handler 异常，不阻塞其他 handler。KillSwitch 是最终安全网——所有风控失败且无法恢复时应触发 KillSwitch 而非忽略错误。

日志实现：`quantflow/monitoring/logger.py` 的 `setup_logging()` 通过 `structlog.stdlib.ProcessorFormatter` 桥接 stdlib `logging`——所有 `logging.getLogger` 调用与原生 structlog 调用共享同一 processor pipeline（`foreign_pre_chain` 接入 stdlib 记录，`wrap_for_formatter` 接入原生记录），统一渲染为结构化输出。新模块用 `logging.getLogger(__name__)` 即可自动结构化，无需直接 import structlog。
</spec-entry>

<spec-entry category="debug" keywords="VectorBTEngine,BacktestEngine,重命名,import-error" date="2026-06-02" sid="S-legacy-99946e76">
### VectorBTEngine → BacktestEngine 重命名
`backtest.py` 中的 `VectorBTEngine` 已重命名为 `BacktestEngine`（纯 pandas/numpy 实现，不依赖 VectorBT）。所有引用（`__init__.py`、`optimizer.py`、`cli/main.py`、`validation/cpcv.py`、`validation/pbo.py`、`validation/wfo.py`、`tests/unit/test_backtest.py`）已同步更新。若新建代码引用 `VectorBTEngine`，将导致 ImportError。
</spec-entry>

<spec-entry category="debug" keywords="e712,ruff,autofix,pandas,numpy,bool" date="2026-07-05" title="E712 on pandas/numpy bools: use bool(x), never accept the `is True` autofix" description="ruff E712 unsafe autofix rewrites ==True to is True, which is False for np.bool_ — silently weakens assertions" sid="S-legacy-c8490c16">
### E712 on pandas/numpy bools: use bool(x), never accept the `is True` autofix

ruff E712 flags `x == True`. Its **unsafe** autofix rewrites to `x is True`. For `numpy.bool_` / pandas scalars, `np.bool_(True) is True` evaluates to `False` (identity comparison against the singleton `True`), so the autofix **silently weakens the assertion** — the test starts passing for the wrong reason, or passes when it should fail.

Fix: for each E712 hit on a pandas/numpy scalar, replace `assert x == True` with `assert bool(x)` (and `== False` → `assert not bool(x)`). Never accept the `is True` / `is False` autofix on data-adjacent code without a manual check.

Why the obvious fix fails: `is True` is the lint-tool's suggested rewrite and looks correct, but identity comparison against the singleton `True` is `False` for numpy bools — a subtle semantic break that tests won't catch (they pass either way).

Detection: review every E712 hit in `tests/unit/test_*.py` that touches pandas DataFrames / numpy arrays / `.iloc` / `.loc` before accepting autofix.

Source: odyssey-debug ci-ruff-breakage session (P2, manual fix in test_runtime_extra.py).
</spec-entry>

<spec-entry category="debug" keywords="yaml,pydantic,schema-drift,config-dropped,silently-ignored" date="2026-07-05" title="YAML key without a matching pydantic field is silently dropped at load time" description="A default.yaml key with no model field is decorative; consumer hardcodes the same default so tests pass — config changes have zero effect" sid="S-legacy-81cd71dd">
### YAML key without a matching pydantic field is silently dropped at load time

A `default.yaml` key with no matching `RiskConfig`/`ExecutionConfig`/`AppConfig` pydantic field is silently dropped at load time. The consumer hardcodes the same default, so tests pass — but the YAML is decorative. An operator tuning that value sees **zero** change.

Recurring instances: `risk.kelly_fraction` (fixed), `risk.var_confidence` (fixed), `risk.position_limit_pct * 100` units bug (the clamp was a no-op for the entire project lifetime because of a separate `*100` units defect). Same class of bug.

Fix template: (1) add the field to the pydantic model with the same default as the YAML; (2) consume it from `self._config.*` instead of a hardcoded literal (config is the single source of truth — never hardcode a literal that duplicates a YAML default); (3) add a schema-drift guard test.

Durable guard: `tests/unit/test_config.py::TestConfigSchemaDrift::test_default_yaml_has_no_dropped_keys` walks `default.yaml` vs `AppConfig` and fails on any scalar key without a matching model field. This locks the `kelly_fraction`/`var_confidence` class of bug from recurring.

Source: odyssey-debug position-sizing-regression session (L1) + odyssey-review deepfix session (Pattern 4, I15).
</spec-entry>


<spec-entry category="debug" keywords="cwe-532,cwe-209,gateway,re-raise,credential-exposure,redaction" date="2026-07-24" sid="S-20260724-ne4k" title="CWE-532 gateway re-raise 致下游 unguarded" description="gateway scrub 自己日志但 re-raise raw 异常；下游 sink（含 HTTP response）unguarded；choke point 缺失" source="main@bb3c6cd">

### CWE-532 gateway re-raise 致下游 unguarded

网关（okx_gateway）用 _safe_error scrub 自己的日志，但 re-raise raw CCXT 异常——异常对象本身仍带 apiKey/URL，下游 caller 接住后若直接 logger.error('%s', e) / f'...: {e}' / print(e) 即泄漏。最隐蔽 sink 是 kill_switch.results['errors'] 追加 raw f-string，该 dict 经 SessionManager.trigger_kill_switch -> web/app.py json_response(result) 进 HTTP response（不是 log，易被忽略），OKX creds 直达客户端。root cause 不是单个 sink 缺 scrub，是 choke point 缺失：修复必须 gate 在 choke point，每个消费 sink 都 scrub（redact_secrets(str(e))），不能只靠 gateway 内部。静态 guard test_credential_bearing_modules_have_redaction_choke_point 守护。

</spec-entry>

<spec-entry category="debug" keywords="partial,降级,submitted,状态白名单,partial-fill" date="2026-07-25" sid="S-20260725-33y2" title="PARTIAL 状态静默降级 bug: ExecutionEngine.submit 原 line 200 'if order.status not in (FILLED, REJECTED): order.status = SUBMITTED' 把 PARTIAL 静默降级为 SUBMITTED, 丢弃 partial fill(不调 L4 增量更新)。修复: 改为 not in (FILLED, PARTIAL, REJECTED) 才降级 SUBMITTED — PARTIAL 保留为 terminal-enough 状态驱动 L4 incremental update。pre-Wave4 未触发因 PaperGateway 立即 FILLED, 但 OKX limit 部分成交会返回 PARTIAL 被吞。根因: 状态白名单漏 PARTIAL。验证: test_execution.py TestCumulativeFillContract 2 新测试 + _PartialFillGateway。" description="PARTIAL 静默降级 SUBMITTED bug 修复: 状态白名单补 PARTIAL" source="main@06a8d93">

### PARTIAL 状态静默降级 bug: ExecutionEngine.submit 原 line 200 'if order.status not in (FILLED, REJECTED): order.status = SUBMITTED' 把 PARTIAL 静默降级为 SUBMITTED, 丢弃 partial fill(不调 L4 增量更新)。修复: 改为 not in (FILLED, PARTIAL, REJECTED) 才降级 SUBMITTED — PARTIAL 保留为 terminal-enough 状态驱动 L4 incremental update。pre-Wave4 未触发因 PaperGateway 立即 FILLED, 但 OKX limit 部分成交会返回 PARTIAL 被吞。根因: 状态白名单漏 PARTIAL。验证: test_execution.py TestCumulativeFillContract 2 新测试 + _PartialFillGateway。



</spec-entry>