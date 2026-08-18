---
title: "Test Conventions"
readMode: required
priority: high
category: test
keywords:
  - test
  - coverage
  - mock
  - fixture
  - assertion
  - framework
related:
  - DOC-knowledge-hub
type: spec
---
# Test Conventions

Auto-generated from project analysis. Update manually as patterns evolve.

## Framework
- Framework: pytest 8.0+ with pytest-asyncio 0.23+
- Run command: `pytest tests/ -v`
- Coverage command: `pytest tests/ --cov=quantflow --cov-report=html`
- asyncio_mode = "auto"

## Directory Structure
- Pattern: tests/unit/ + tests/integration/
- Shared fixtures: tests/conftest.py

## Naming Conventions
- Test files: test_*.py
- Test classes: PascalCase (TestAppConfig, TestBar, TestSignal)
- Test functions: snake_case (test_fetch_ohlcv, test_generate_signals)

## Markers
- `@pytest.mark.slow` — 慢测试
- `@pytest.mark.integration` — 集成测试（需要真实数据流）
- `@pytest.mark.live` — Live 测试（需要 API 连接）

## Coverage
- Threshold: >70% (核心模块)
- Source: quantflow
- Omit: tests/*, quantflow/cli/*

## Patterns
- 基于 pytest fixtures（conftest.py 提供 AppConfig、sample Bar）
- 不使用 unittest.TestCase
- 集成测试需要真实数据流，禁止 mock 掩盖失败
- 禁止 @skip/@ignore 掩盖测试失败，必须修复根因
- **SRP 拆分后必配命名单元测试**：从 god-object 抽出的纯职责组件配独立测试文件。范式：`tests/unit/test_order_router.py`（ISS-003 从 ExecutionEngine 抽 OrderRouter，9 测试覆盖 route/build_order/build_close_request/is_closeable/set_gateway，独立于 submit 编排）。命名测试让抽出组件可单独验证，不依赖宿主编排。
- **OBS-M（observability）注入测试**：Protocol 扩展的新 sink 方法配接入测试。范式：`tests/unit/test_monitoring_sink_obs.py`（ISS-011，8 测试覆盖 Null no-op + connect/disconnect/reconnect/timeout 接入 + risk details，用 `_RecordingSink(NullMonitoringSink)` 子类化记录调用）。验证 L5 组件经 sink Protocol 发指标而非直接 import L6。
- **静态源文件正则 guard（choke-point 单一审计面）**：对单一审计面 security primitive（`setHTML` XSS choke-point / `validate_symbol`）配"读源码 + 正则断言"测试，CI 时拦截 choke-point 绕过。范式：`tests/unit/test_innerhtml_choke_point.py`（ISS-UX-20260728，读 `app.js` 源文本，正则断言 `setHTML` 函数存在 + `metricCard` string/label 分支 `escapeHtml` wrap）。仿 `validate_symbol` 单一审计面范式——guard 不测运行时行为（JS 无单测框架），测"choke-point 仍在位且 escape 闭环"的结构不变量。
- **config schema drift guard（hardcoded→config 迁移守卫）**：hardcoded 默认值迁移到 Pydantic config 字段时，配双向守卫 + baseline 对齐断言，保迁移不破 backtest baseline。范式：`TestConfigSchemaDrift`（YAML↔pydantic 双向字段对齐）+ `test_config_sourced_defaults` / `test_risk_config_wires_fixed_pct_and_min_order_notional` / `test_execution_taker_fee_wired`（ISS-012，断言 config 默认值 byte-for-byte 等于原硬编码 0.10/10.0/0.001，且字段透传到消费者 `PositionSizer` 构造）。

<spec-entry category="test" keywords="测试,单元测试,集成测试,覆盖率,mock" date="2026-05-29" sid="S-legacy-58dc480c">
### 测试分层与覆盖率要求
核心模块（data/indicators/strategy/validation/execution/risk）必须有单元测试，覆盖率 >70%。测试分三层：unit（单模块）、integration（跨模块端到端）、conftest 共享 fixture。集成测试需要真实数据流而非 mock。禁止用 @skip/@ignore 掩盖测试失败，必须修复根因。

> **2026-08-18 v0.8.0 更新（sid S-20260818-cov100）**：覆盖率门禁已提升到 **行+分支双 100%**（`pyproject.toml [tool.coverage.report] fail_under=100`，`--cov-branch` 实测 TOTAL 18568 stmts / 5386 branches 全 0 缺失，3423 tests）。验收命令：`.venv/Scripts/python.exe -m pytest tests/ --cov=quantflow --cov-branch --cov-report=term-missing -m "not live"`。新增 35 个 `tests/unit/test_coverage_*.py` 文件（约 1400 用例）覆盖全层。pragma 豁免规则：`# pragma: no cover`/`# pragma: no branch` 仅用于真正不可达/外部 IO 路径（__main__ 守卫、合成数据恒正、循环不变式、elif 链短路、AST 负数表示），必须附理由注释；禁止掩盖可测分支。错误断言测试直接删除而非 @skip 掩盖。
</spec-entry>

<spec-entry category="test" keywords="asyncio,装饰器,async,pytest-asyncio,false-negative" date="2026-07-31" sid="S-20260731-a7k2" title="async 测试方法必须添加 @pytest.mark.asyncio 装饰器" description="类中 async def test_* 缺少装饰器会被跳过导致 false negative" source="phase-6-codereview">

### async 测试方法必须添加 @pytest.mark.asyncio 装饰器

所有定义在 class 中的 `async def test_*` 方法必须显式添加 `@pytest.mark.asyncio` 装饰器。缺少装饰器时 pytest-asyncio 会跳过该测试（或将其当作同步函数执行而不 await），导致测试显示 passed 但实际未执行——这是 false negative，比显式失败更危险。

**注意**: `pyproject.toml` 的 `asyncio_mode = "auto"` 仅对**模块级** async 函数自动生效。类方法中的 `async def` 仍需显式装饰器。Phase 6 CodeReview (Ryan) 在 `test_m4_killswitch_threadflush.py` 中发现 3 个缺失装饰器的 Critical Issue，已修复。

**守卫**: ruff 规则 `RUF100` + 手动 grep `async def test_` 后检查上方是否有 `@pytest.mark.asyncio`。新增 async 测试时立即添加装饰器。
</spec-entry>