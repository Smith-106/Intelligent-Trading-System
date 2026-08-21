"""Recursive indicator dependency analysis (ISS-20260718-002).

Detects circular dependencies between indicator computations.
When indicator A depends on indicator B, and B depends on A,
a recursive cycle is formed that can cause incorrect results
or infinite loops in computation order.

CLI: ``quantflow validate --strategy <name> --method recursive``
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RecursiveReport:
    """Report from recursive indicator dependency scan."""

    strategy: str
    passed: bool
    cycles: list[list[str]] = field(default_factory=list)
    indicator_deps: dict[str, list[str]] = field(default_factory=dict)
    source_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "passed": self.passed,
            "cycles": self.cycles,
            "indicator_deps": self.indicator_deps,
        }


def scan_recursive(strategy_class: type) -> RecursiveReport:
    """Scan a strategy class for recursive indicator dependencies.

    Analyzes the strategy's generate_signals() and on_bar() methods
    to build an indicator dependency graph, then detects cycles via DFS.

    Args:
        strategy_class: Strategy class to analyze

    Returns:
        RecursiveReport with cycle detection results
    """
    strategy_name = getattr(strategy_class, "name", strategy_class.__name__)

    # Get source file path
    try:
        source_file = inspect.getfile(strategy_class)
        source_path = str(Path(source_file).resolve())
    except (TypeError, OSError):
        source_path = None

    # Build dependency graph from strategy source
    deps = _extract_indicator_deps(strategy_class)

    # Detect cycles via DFS
    cycles = _detect_cycles(deps)

    return RecursiveReport(
        strategy=strategy_name,
        passed=len(cycles) == 0,
        cycles=cycles,
        indicator_deps=deps,
        source_path=source_path,
    )


def _extract_indicator_deps(strategy_class: type) -> dict[str, list[str]]:
    """Extract indicator dependencies from strategy source code.

    Parses the strategy's source to find calls to indicator compute methods
    and builds a dependency graph.
    """
    try:
        source = inspect.getsource(strategy_class)
    except (TypeError, OSError):
        return {}

    tree = ast.parse(source)
    deps: dict[str, list[str]] = {}

    # Walk AST looking for method calls that reference indicators
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            method_name = node.name
            indicator_calls: list[str] = []
            for child in ast.walk(node):
                if isinstance(child, ast.Attribute):
                    # Look for patterns like: self.rsi.compute(), self.macd.compute()
                    if isinstance(child.value, ast.Attribute):
                        if hasattr(
                            child.value, "attr"
                        ):  # pragma: no branch — Attribute nodes always carry .attr
                            indicator_calls.append(child.value.attr)
                    # Look for: IndicatorEngine.compute_all, engine.compute()
                    elif isinstance(child.value, ast.Name):
                        if child.attr in ("compute_all", "compute"):
                            indicator_calls.append(child.value.id)
            if indicator_calls:
                deps[method_name] = list(set(indicator_calls))

    return deps


def _detect_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """Detect cycles in a directed graph using DFS.

    Returns list of cycles found (each cycle is a list of node names).
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {node: WHITE for node in graph}
    # Also add destination nodes that aren't keys
    for _node, neighbors in graph.items():
        for n in neighbors:
            if n not in color:
                color[n] = WHITE

    cycles: list[list[str]] = []
    path: list[str] = []

    def dfs(node: str) -> None:
        color[node] = GRAY
        path.append(node)

        for neighbor in graph.get(node, []):
            if color.get(neighbor, WHITE) == GRAY:
                # Found cycle: extract it from path
                cycle_start = path.index(neighbor)
                cycle = [*path[cycle_start:], neighbor]
                cycles.append(cycle)
            elif color.get(neighbor, WHITE) == WHITE:
                dfs(neighbor)

        path.pop()
        color[node] = BLACK

    for node in list(color.keys()):
        if color[node] == WHITE:
            dfs(node)

    return cycles
