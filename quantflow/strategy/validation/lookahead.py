"""Static look-ahead leak detector for vectorized signal generators.

Deep-research F2 / P0.2: a vectorized ``generate_signals(df)`` that aggregates
over a boolean entry/exit mask — e.g. ``series[entries].mean()`` — uses
**future** bar data at the entry bar. The masked values are computed from the
full series, so the entry-bar value already reflects information only known
later (the canonical v0.1.3 look-ahead regressions: trend_following RSI
profit-target, momentum_rotation cross-sectional rank, FLAT-as-SELL).

Unlike Freqtrade's runtime ``lookahead-analysis`` (which perturbs a backtest
to provoke leakage), this detector does a static AST scan of a strategy's
``generate_signals`` source — it flags the masked-aggregation pattern
directly, no data or backtest required. The fix is to capture the value at
the entry bar and forward-fill it for the position lifetime (canonical
helper: ``profit_target_exit_series`` in ``strategy/templates/_runtime.py``).

CLI: ``quantflow validate --strategy <name> --method lookahead``
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Iterable
from dataclasses import dataclass, field

from quantflow.strategy.base import StrategyBase

# Names treated as boolean entry/exit/mask selectors when used as a subscript
# slice. Conservative: only flag well-known mask names, not arbitrary names,
# to keep the false-positive rate low.
_MASK_NAMES: frozenset[str] = frozenset(
    {"entries", "exits", "mask", "signals", "long_mask", "short_mask", "entry_mask", "exit_mask"}
)

# Aggregation calls that, applied to a masked series, mix future-bar values
# into the entry-bar decision.
_AGG_METHODS: frozenset[str] = frozenset(
    {
        "mean",
        "sum",
        "std",
        "var",
        "median",
        "min",
        "max",
        "quantile",
        "agg",
        "aggregate",
        "describe",
        "skew",
        "kurt",
        "kurtosis",
        "cumsum",
        "cummax",
        "cummin",
        "cumprod",
        "rank",
        "nlargest",
        "nsmallest",
    }
)

# Rolling/expanding window calls likewise leak when their input is a mask slice
# of the full series, because the window may extend into future bars relative
# to the entry bar.
_WINDOW_METHODS: frozenset[str] = frozenset({"rolling", "expanding", "ewm", "resample"})


@dataclass(frozen=True)
class LookaheadFinding:
    """One detected look-ahead leak candidate."""

    strategy: str
    method: str
    pattern: str  # human-readable, e.g. "series[entries].mean()"
    line: int
    column: int
    snippet: str
    severity: str  # "high" | "medium"
    note: str


@dataclass
class LookaheadReport:
    """Result of scanning one strategy."""

    strategy: str
    findings: list[LookaheadFinding] = field(default_factory=list)
    scanned_methods: list[str] = field(default_factory=list)
    source_path: str | None = None

    @property
    def passed(self) -> bool:
        """True when no look-ahead leak candidates were found."""
        return not self.findings

    @property
    def high_severity_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "high")

    def summary(self) -> str:
        if self.passed:
            return f"{self.strategy}: PASS (no masked-aggregation leaks)"
        return (
            f"{self.strategy}: FAIL — {len(self.findings)} leak candidate(s) "
            f"({self.high_severity_count} high)"
        )


def _slice_is_mask(slice_node: ast.AST) -> bool:
    """True when a subscript slice is a known boolean mask name."""
    # Python 3.9+: Subscript.slice is the expression directly. (QuantFlow
    # targets 3.11+, so no ast.Index unwrapping is needed.)
    return isinstance(slice_node, ast.Name) and slice_node.id in _MASK_NAMES


def _masked_subscript_pattern(node: ast.AST) -> str | None:
    """If ``node`` is ``series[mask]`` return a label, else None."""
    if isinstance(node, ast.Subscript) and _slice_is_mask(node.slice):
        value_name = _attr_chain(node.value)
        slice_name = _slice_name(node.slice)
        return f"{value_name}[{slice_name}]"
    return None


def _attr_chain(node: ast.AST) -> str:
    """Render an attribute/value chain like ``df.close`` or ``rsi``."""
    if isinstance(node, ast.Attribute):
        return f"{_attr_chain(node.value)}.{node.attr}"
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Subscript):
        return f"{_attr_chain(node.value)}[...]"
    return "<expr>"


def _slice_name(slice_node: ast.AST) -> str:
    if isinstance(slice_node, ast.Name):
        return slice_node.id
    return "<?>"


def _scan_node(
    node: ast.AST,
    findings: list[LookaheadFinding],
    strategy: str,
    method: str,
    source_lines: list[str],
) -> None:
    """Walk ``node`` and append findings for masked-aggregation patterns.

    Two shapes are flagged:
      1. ``series[mask].<agg>(...)`` — direct aggregation on a mask slice,
         including chained window calls (``series[mask].rolling(...).mean()``).
      2. ``<agg>(series[mask])`` — aggregation function wrapping a mask slice
         (e.g. ``np.mean(series[entries])``). Covers both bare ``mean(...)`` and
         ``np.mean(...)`` / ``pd.Series.mean(...)`` attribute calls.

    A masked subscript is only flagged once: the innermost aggregation site.
    """
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func

        # Shape 1: <x>.<agg>(...) where x is series[mask] or a chain on it.
        if isinstance(func, ast.Attribute):
            recv = func.value
            # direct: series[mask].mean()
            pattern = _masked_subscript_pattern(recv)
            if pattern is not None and func.attr in _AGG_METHODS:
                findings.append(
                    _make_finding(
                        strategy, method, child, f"{pattern}.{func.attr}()", source_lines, "high"
                    )
                )
                continue
            # chain: series[mask].rolling(...).mean() — flag the outer agg,
            # not also the inner rolling() call (avoids duplicate findings).
            if isinstance(recv, ast.Call) and isinstance(recv.func, ast.Attribute):
                inner_recv = recv.func.value
                inner_pattern = _masked_subscript_pattern(inner_recv)
                if inner_pattern is not None and recv.func.attr in _WINDOW_METHODS:
                    findings.append(
                        _make_finding(
                            strategy,
                            method,
                            child,
                            f"{inner_pattern}.{recv.func.attr}(...).{func.attr}()",
                            source_lines,
                            "high",
                        )
                    )
                    continue

        # Shape 2: agg(series[mask]) — bare Name or np.<agg> attribute call
        # wrapping a masked subscript as its first positional arg.
        agg_name = ""
        if isinstance(func, ast.Name):
            agg_name = func.id
        elif isinstance(func, ast.Attribute):
            agg_name = func.attr
        if agg_name in _AGG_METHODS and child.args:
            first = child.args[0]
            pattern = _masked_subscript_pattern(first)
            if pattern is not None:
                # Skip if this same Call was already flagged as Shape 1
                # (series[mask].agg() has the mask on the receiver, not arg0).
                findings.append(
                    _make_finding(
                        strategy, method, child, f"{agg_name}({pattern})", source_lines, "medium"
                    )
                )


def _make_finding(
    strategy: str, method: str, node: ast.AST, pattern: str, source_lines: list[str], severity: str
) -> LookaheadFinding:
    line = getattr(node, "lineno", 0)
    col = getattr(node, "col_offset", 0)
    snippet = ""
    if 0 < line <= len(source_lines):
        snippet = source_lines[line - 1].strip()
    note = (
        "Aggregation over a boolean mask mixes future-bar values into the "
        "entry-bar decision (look-ahead). Capture the entry-bar value and "
        "forward-fill it for the position lifetime "
        "(profit_target_exit_series in strategy/templates/_runtime.py)."
    )
    return LookaheadFinding(
        strategy=strategy,
        method=method,
        pattern=pattern,
        line=line,
        column=col,
        snippet=snippet,
        severity=severity,
        note=note,
    )


def _method_ast(obj: object, method_name: str) -> tuple[ast.AST, list[str]] | None:
    """Return (AST of method body source, source lines) or None if unavailable."""
    func = getattr(obj, method_name, None)
    if func is None:
        return None
    try:
        source = inspect.getsource(func)
    except (OSError, TypeError):
        return None
    # inspect.getsource returns the def with original indentation; dedent so
    # ast.parse accepts it as a module-level function body.
    import textwrap

    source = textwrap.dedent(source)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    return tree, source.splitlines()


def scan_strategy(strategy: StrategyBase) -> LookaheadReport:
    """Scan a strategy instance for look-ahead leak patterns in its signal generators.

    Scans ``generate_signals`` (vectorized research/backtest API) by default.
    Also scans ``on_bar`` if present, since incremental paths can leak too.

    Additional pass (IAF): flags ``.shift(-n)`` / ``shift(periods=-n)`` which
    pull future bar values into the current decision (true future function).
    """
    from quantflow.indicators.causal import scan_source_for_negative_shift

    report = LookaheadReport(strategy=type(strategy).__name__)
    try:
        report.source_path = inspect.getsourcefile(type(strategy)) or None
    except (OSError, TypeError):
        report.source_path = None

    for method_name in ("generate_signals", "on_bar"):
        parsed = _method_ast(strategy, method_name)
        if parsed is None:
            continue
        tree, lines = parsed
        report.scanned_methods.append(method_name)
        _scan_node(tree, report.findings, report.strategy, method_name, lines)
        # Negative shift scan on the same method source
        try:
            src = inspect.getsource(getattr(strategy, method_name))
        except (OSError, TypeError):
            continue
        for hit in scan_source_for_negative_shift(src, where=method_name):
            report.findings.append(
                LookaheadFinding(
                    strategy=report.strategy,
                    method=method_name,
                    pattern=hit.detail,
                    line=hit.line,
                    column=0,
                    snippet=hit.snippet,
                    severity="high",
                    note=(
                        "Negative shift is an explicit future function: value at t "
                        "depends on t+|n|. Use lag (shift(+n)) or decision lag via "
                        "quantflow.indicators.causal.shift_for_trade."
                    ),
                )
            )

    return report


def scan_strategies(strategies: Iterable[StrategyBase]) -> list[LookaheadReport]:
    """Scan multiple strategies and return one report each."""
    return [scan_strategy(s) for s in strategies]
