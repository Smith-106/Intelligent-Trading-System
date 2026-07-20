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

<spec-entry category="coding" keywords="validate-symbol,write-path,path-traversal,choke-point,symmetric-validation" date="2026-07-05" title="Validate symbol at EVERY symbol→path/glob site — read, write, AND in-place transform" description="Write/transform paths must call validate_symbol symmetric with reads; a direct Path construction bypasses the DataStore choke point">
### Validate symbol at EVERY symbol→path/glob site — read, write, AND in-place transform

Every code path that turns a user/operator-supplied symbol into a filesystem path OR a DuckDB glob literal must pass through `quantflow.common.validators.validate_symbol()`. This includes:

- **Read paths** — `DataStore.query`, `get_date_range`, `FeatureStore.load_features` (validate before interpolating into `read_parquet('...{symbol}...')`).
- **Write paths** — `DataStore.save`, `FeatureStore.save_features` (validate before `Path(parquet_dir)/symbol_name`).
- **In-place transform paths** — any service-layer handler that constructs a `Path` directly (e.g. `web/service.py:tag_data_source`). Do NOT rely on "the downstream DataStore call validates" — a direct `Path` construction runs FIRST and bypasses the choke point.

Anti-pattern: `symbol.replace('/', '_')` without `validate_symbol` — leaves a path-traversal (CWE-22) + SQL-injection-via-glob (CWE-89) surface. The read path validated but the write/transform path didn't (asymmetric validation).

The choke point is `validate_symbol` (public, not underscored — see arch spec on security primitives). `SYMBOL_PATTERN` rejects quotes, backslashes, dots, glob metachars (`*` `[`), shell metachars, spaces, and >20-char strings.

Durable guard: `tests/unit/test_trend_and_store.py::test_validate_symbol_rejects_security_relevant_chars` (14 parametrized cases).

Source: odyssey-review security-fixes session (REV-008 + sibling G4 in service.py).
</spec-entry>

<spec-entry category="coding" keywords="auto-commit,ruff,lint-gate,pre-commit,workflow-discipline" date="2026-07-05" title="Run ruff check --fix && ruff format before every auto-commit (lint-before-commit gate)" description="Workflow phase auto-commits must lint/format first or CI's ruff gate goes red; defense-in-depth via .pre-commit-config.yaml">
### Run ruff check --fix && ruff format before every auto-commit (lint-before-commit gate)

Any workflow action that does `git add` + `git commit` on generated/edited Python MUST run the project-mandated lint/format pipeline immediately before `git add`, and abort the commit on lint failure:

```bash
ruff check --fix . && ruff format .
if ! ruff check . ; then echo "lint failed; aborting commit"; exit 1; fi
git add <files> && git commit -m "..."
```

Without this gate, every auto-commit can drift past the CI quality bar; errors compound across a multi-phase session (one deepfix session accumulated 200+ ruff errors across 30 test files before anyone noticed). Subagent-generated test files are the most common vector (large, written in bulk, never individually formatted).

Defense-in-depth: a repo-level `.pre-commit-config.yaml` (ruff `--fix` + ruff-format hooks, pinned to the project ruff version) enforces this at the git layer even when the workflow reminder is missed. Both layers are intentional.

Detection: CI `ruff format --check` + `ruff check` go red on `main` shortly after the offending commit; failing files cluster in one command's session window (`git log --oneline -- <file>`). When CI ruff fails on files all from one session, suspect this pattern, not a config change.

Source: odyssey-debug ci-ruff-breakage session (P1). Implemented as a maestro overlay on the odyssey-*.md wrappers + `.pre-commit-config.yaml`.
</spec-entry>

<spec-entry category="coding" keywords="look-ahead,vectorized,signal-generator,entries-mask,forward-fill" date="2026-07-05" title="No look-ahead in vectorized signal generators — never aggregate over entries[bool_mask]" description="series[entries].mean() uses future bar data at the entry bar; capture value at entry + forward-fill for position lifetime">
### No look-ahead in vectorized signal generators — never aggregate over entries[bool_mask]

In a vectorized `generate_signals(df)`, any `series[entries].mean()` / aggregation over a boolean entry mask uses **future** bar data at the entry bar — a look-ahead bug. The masked values are computed from the full series, so the entry-bar value already reflects information only known later.

Fix pattern: capture the value at the entry bar and forward-fill it for the position lifetime. Canonical helper: `profit_target_exit_series` in `strategy/templates/_runtime.py` — computes a per-bar `effective_pct_series` (e.g. RSI-adaptive tight/wide multiplier) forward-filled from the entry bar, so each bar during the position sees only the entry-bar decision.

Scan: all `generate_signals` implementations + indicator factories that consume `entries`/`exits` masks. The v0.1.3 perf run introduced 3 CRITICAL look-ahead regressions (trend_following RSI profit-target, momentum_rotation cross-sectional rank, FLAT-as-SELL). Perf optimization without a correctness gate breeds these — any "perf optimize X" change MUST be followed by a look-ahead audit of the vectorized signal path before merge.

Source: odyssey-review deepfix session (Pattern 1, CRITICAL fixes 1-3).
</spec-entry>


<spec-entry category="coding" keywords="vectorbt,参数扫描,向量化,multi-asset,broadcasting" date="2026-07-18" sid="S-20260718-sffn" title="研究层大规模参数扫描用 vectorbt run_combs/Portfolio.from_signals 多资产 broadcasting" description="用 run_combs/Portfolio.from_signals 多资产 broadcasting 替代 Python 循环做大规模参数扫描" source="harvest:deep-research-20260718">

### 研究层大规模参数扫描用 vectorbt run_combs/Portfolio.from_signals 多资产 broadcasting

研究层应充分利用 vectorbt 的向量化参数扫描:放弃逐 bar 循环,把数千策略配置打包进 NumPy 数组做向量化评估(Numba+Rust 加速热路径),支持多资产 broadcasting 的大规模参数扫描(如 vbt.MA.run_combs(price, window=np.arange(2,101), r=2) 跨 BTC/ETH/XRP,将小时级网格搜索压缩到秒级)。需核实 strategy/research/ 当前是否仍用 Python 循环,若是则迁移到 run_combs/Portfolio.from_signals。注: vectorbt 活跃维护(2026-07 仍有提交);Numba JIT 路径在小数据集上可能产生 cryptic error 与延迟,热路径需基准测试。来源: deep-research-20260718 F6-参考项目 (3-0 verified), polakowo/vectorbt。

</spec-entry>

<spec-entry category="coding" keywords="compound,strategy_id,allocation,consolidated-signal,exact-lookup,silent-drop" date="2026-07-20" sid="S-20260720-98vs" title="Compound strategy_id 精确查找静默失效" description="compound strategy_id 精确查找静默失效范式——consolidated signal 的 joined key 永远 miss，返回 0.0 致信号丢弃/预算 bypass" source="main@428002d">

### Compound strategy_id 精确查找静默失效

consolidated signal 携带逗号拼接的 compound strategy_id（如 "momentum_rotation,trend_following"）。任何以 strategy_id 为 key 的 dict.get(exact_key, default) / exact-match 查找（allocation、win_rate、hit_rate、risk_budget、order 查询）对 compound key 永远 miss，静默返回 default（通常 0.0）——信号被 size*0 丢弃在 engine.py:313，或 risk budget 被静默 bypass。修复模板：(1) 用 strategy_id_constituents(id) 展开为 constituents list；(2) 对每个 constituent 查找并求和/聚合（allocation 求和、win_rate 加权平均、risk budget 逐 constituent 强制）；(3) 非 compound 时回退原始 raw id 查找。所有消费 compound-key signal 的 dict 必须用此展开。已知修复点：portfolio.get_strategy_allocation (CORR-H1, ISS-20260720 odyssey)、risk_engine._check_strategy_budget (ISS-20260613-006 family)、position_sizer.size win-rate blending。守卫：新写任何 dict[str,X] keyed by strategy_id 的消费者前，grep 确认是否处理 compound。

</spec-entry>