---
title: "Quality Rules"
readMode: required
priority: medium
category: review
keywords:
  - quality
  - lint
  - rule
  - enforcement
related:
  - DOC-knowledge-hub
type: spec
---
# Quality Rules

## Linter
- Tool: ruff (replaces flake8 + isort + pyupgrade)
- Config: pyproject.toml [tool.ruff]
- Line length: 100
- Target: Python 3.11
- Select rules: E, F, I, N, W, UP, B, SIM, RUF
- isort: known-first-party = ["quantflow"]
- Fix command: `ruff check --fix .`

## Formatter
- Tool: ruff format (replaces black)
- Quote style: double
- Indent style: space (4)

## Type Checking
- Tool: mypy --strict
- python_version = "3.11"

## Entries
