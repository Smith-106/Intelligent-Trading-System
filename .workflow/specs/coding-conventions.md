---
title: "Coding Conventions"
category: coding
---
# Coding Conventions

Auto-generated from project analysis. Update manually as patterns evolve.

## Formatting
- Indentation: 4 spaces (Python standard)
- Line length: 100 (ruff)
- Trailing commas: yes (multi-line structures)
- Semicolons: no (Python)

## Naming
- Variables/functions: snake_case
- Classes/types: PascalCase
- Constants: UPPER_SNAKE_CASE
- Files: snake_case.py
- Private methods: _leading_underscore
- Pydantic models: PascalCase
- Enum members: UPPER_SNAKE_CASE

## Imports
- Style: named imports (from ... import ...)
- Path aliases: none (quantflow.xxx absolute imports)
- Order: stdlib → third-party → first-party (ruff isort, known-first-party = ["quantflow"])
- Always use `from __future__ import annotations`

## Patterns
- Type annotations on all function signatures (return types + params)
- Use `|` union syntax (Python 3.10+ style)
- Google/NumPy docstrings on classes and public methods
- Pydantic v2 for config/data validation
- structlog for structured logging
- async/await throughout (CCXT async, WebSocket, gateway)
- Abstract base classes for interfaces (StrategyBase, GatewayBase, FactorBase)

## Entries

<spec-entry category="coding" keywords="策略双模式,generate_signals,on_bar,向量化,事件驱动" date="2026-06-13" title="策略双模式: generate_signals 向量化 + on_bar 事件驱动" description="策略模板标准双 API 模式">
### 策略双模式: generate_signals 向量化 + on_bar 事件驱动

所有策略模板遵循双模式：
1. `generate_signals(df)` — 向量化研究/回测 API，输入完整 DataFrame，输出 (entries, exits) boolean Series
2. `on_bar(ctx, bar)` — 事件驱动 live/paper API，接收单根 bar，通过 emit_signal 生成信号

两种模式必须保证信号 parity，通过确定性 fixture 测试验证。

**来源**: PLAN-001 DD-004 设计决策
**模式参考**: trend_following.py 双模式实现
</spec-entry>

<spec-entry category="coding" keywords="search,codegraph,代码搜索" date="2026-06-01">

### mcp-semantic-search

代码搜索优先使用 CodeGraph MCP（`mcp__codegraph__codegraph_context`），精确符号查找用 `codegraph_search`/`codegraph_callers`，简单文本匹配用 Grep

</spec-entry>
