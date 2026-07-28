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

<spec-entry category="test" keywords="测试,单元测试,集成测试,覆盖率,mock" date="2026-05-29">
### 测试分层与覆盖率要求
核心模块（data/indicators/strategy/validation/execution/risk）必须有单元测试，覆盖率 >70%。测试分三层：unit（单模块）、integration（跨模块端到端）、conftest 共享 fixture。集成测试需要真实数据流而非 mock。禁止用 @skip/@ignore 掩盖测试失败，必须修复根因。
</spec-entry>