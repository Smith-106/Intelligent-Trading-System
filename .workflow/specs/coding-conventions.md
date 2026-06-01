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

<spec-entry category="coding" keywords="search,codegraph,代码搜索" date="2026-06-01">

### mcp-semantic-search

代码搜索优先使用 CodeGraph MCP（`mcp__codegraph__codegraph_context`），精确符号查找用 `codegraph_search`/`codegraph_callers`，简单文本匹配用 Grep

</spec-entry>
