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

<spec-entry category="test" keywords="测试,单元测试,集成测试,覆盖率,mock" date="2026-05-29">
### 测试分层与覆盖率要求
核心模块（data/indicators/strategy/validation/execution/risk）必须有单元测试，覆盖率 >70%。测试分三层：unit（单模块）、integration（跨模块端到端）、conftest 共享 fixture。集成测试需要真实数据流而非 mock。禁止用 @skip/@ignore 掩盖测试失败，必须修复根因。
</spec-entry>