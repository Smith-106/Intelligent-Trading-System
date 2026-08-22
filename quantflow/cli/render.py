"""Rich rendering helpers for CLI validation output (REV-009/S4).

Moved verbatim out of ``cli.main`` (~230 lines of stateless display functions).
``main.py`` re-imports these names so external imports or monkeypatches on
``quantflow.cli.main._display_*`` keep working.
"""

from __future__ import annotations

from typing import Any, TypeAlias

from rich.console import Console
from rich.table import Table

from quantflow.strategy.validation.lookahead import LookaheadReport
from quantflow.strategy.validation.monte_carlo import MonteCarloResult
from quantflow.strategy.validation.recursive import RecursiveReport

console = Console()

ResultDict: TypeAlias = dict[str, Any]


def _display_cpcv(result: ResultDict) -> None:
    table = Table(title="CPCV Validation Results")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Paths", str(result["n_paths"]))
    table.add_row("PBO", f"{result['pbo']:.3f}")
    table.add_row("OOS Efficiency", f"{result['oos_efficiency']:.3f}")
    table.add_row(
        "OOS Sharpe (mean±std)", f"{result['oos_sharpe_mean']:.3f}±{result['oos_sharpe_std']:.3f}"
    )
    table.add_row("OOS Sharpe (min)", f"{result['oos_sharpe_min']:.3f}")
    _add_signal_quality_rows(table, result.get("signal_quality", {}))
    status = "[green]PASSED[/]" if result["passed"] else "[red]FAILED[/]"
    table.add_row("Status", status)
    console.print(table)


def _display_dsr(result: ResultDict) -> None:
    table = Table(title="Deflated Sharpe Ratio")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("DSR", f"{result['dsr']:.4f}")
    table.add_row("Observed Sharpe", f"{result['observed_sharpe']:.3f}")
    table.add_row(
        "Expected Max (N trials)", f"{result['expected_max_sharpe']:.3f} (N={result['n_trials']})"
    )
    status = "[green]PASSED[/]" if result["passed"] else "[red]FAILED[/]"
    table.add_row("Status", status)
    console.print(table)


def _display_wfo(rolling: ResultDict, anchored: ResultDict) -> None:
    table = Table(title="Walk-Forward Optimization")
    table.add_column("Metric", style="cyan")
    table.add_column("Rolling", style="green")
    table.add_column("Anchored", style="green")
    table.add_row(
        "IS Sharpe", f"{rolling['is_sharpe_mean']:.3f}", f"{anchored['is_sharpe_mean']:.3f}"
    )
    table.add_row(
        "OOS Sharpe", f"{rolling['oos_sharpe_mean']:.3f}", f"{anchored['oos_sharpe_mean']:.3f}"
    )
    table.add_row(
        "OOS Efficiency", f"{rolling['oos_efficiency']:.3f}", f"{anchored['oos_efficiency']:.3f}"
    )
    for label, key in _SIGNAL_QUALITY_ROWS:
        table.add_row(
            label,
            _format_signal_quality(rolling.get("signal_quality", {}), key),
            _format_signal_quality(anchored.get("signal_quality", {}), key),
        )
    r_status = "PASSED" if rolling["passed"] else "FAILED"
    a_status = "PASSED" if anchored["passed"] else "FAILED"
    table.add_row("Decision", r_status, a_status)
    console.print(table)


def _display_pbo(result: ResultDict) -> None:
    table = Table(title="Probability of Backtest Overfitting")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("PBO", f"{result['pbo']:.3f}")
    table.add_row("Overfit Paths", f"{result['overfit_paths']}/{result['total_paths']}")
    table.add_row("IS Return (mean)", f"{result['is_return_mean']:.3f}")
    table.add_row("OOS Return (mean)", f"{result['oos_return_mean']:.3f}")
    table.add_row("Rank Correlation", f"{result['rank_correlation']:.3f}")
    status = "[green]PASSED[/]" if result["passed"] else "[red]FAILED[/]"
    table.add_row("Status", status)
    console.print(table)


def _display_gate(result: ResultDict) -> None:
    console.print(f"\n[bold]VALIDATION GATE: {result['decision']}[/]")
    if "reason" in result:
        console.print(f"Reason: {result['reason']}")
    for check_name, check_result in result.get("checks", {}).items():
        passed = check_result.get("passed", False)
        status = "[green]OK[/]" if passed else "[red]ERR[/]"
        console.print(f"  {status} {check_name}")
        if check_result.get("signal_quality"):
            console.print(f"    Signal quality: {_signal_quality_summary(check_result)}")
    console.print()


def _display_causal_preflight(report: Any) -> None:
    """Render causal preflight (lookahead + negative-shift) result."""
    color = "green" if report.passed else "red"
    console.print(f"\n[bold {color}]{report.summary()}[/]")
    counts = report.severity_counts or {}
    console.print(
        f"Severity: high={counts.get('high', 0)} medium={counts.get('medium', 0)} "
        f"low={counts.get('low', 0)}"
    )
    if report.lookahead:
        la = report.lookahead
        console.print(
            f"Lookahead: {'PASS' if la.get('passed') else 'FAIL'} "
            f"scanned={', '.join(la.get('scanned_methods') or []) or '(none)'}"
        )
    if report.negative_shifts:
        table = Table(title=f"Negative shift findings ({len(report.negative_shifts)})")
        table.add_column("Where", style="cyan")
        table.add_column("Line", justify="right")
        table.add_column("Snippet")
        for hit in report.negative_shifts:
            table.add_row(
                str(hit.get("where", "")),
                str(hit.get("line", "")),
                str(hit.get("snippet", ""))[:60],
            )
        console.print(table)
    if report.passed:
        console.print("[green]No high-severity causal leaks detected.[/]")
    else:
        console.print("[yellow]Fix high findings before dual-path gate / promotion research.[/]")
    for note in report.notes or []:
        console.print(f"[dim]note: {note}[/]")
    console.print()


def _display_lookahead(report: LookaheadReport) -> None:
    """Render a static look-ahead scan report for one strategy."""
    verdict = "PASS" if report.passed else "FAIL"
    color = "green" if report.passed else "red"
    console.print(f"\n[bold {color}]LOOK-AHEAD SCAN: {report.strategy} — {verdict}[/]")
    console.print(f"Scanned: {', '.join(report.scanned_methods) or '(no generate_signals found)'}")
    if report.source_path:
        console.print(f"Source: {report.source_path}")
    if report.passed:
        console.print("[green]No masked-aggregation leaks detected.[/]")
        console.print()
        return
    table = Table(title=f"Look-ahead findings ({len(report.findings)})")
    table.add_column("Sev", style="cyan", no_wrap=True)
    table.add_column("Line", justify="right", no_wrap=True)
    table.add_column("Pattern", style="magenta")
    table.add_column("Snippet")
    for f in report.findings:
        sev_color = "bold red" if f.severity == "high" else "yellow"
        table.add_row(f"[{sev_color}]{f.severity}[/]", str(f.line), f.pattern, f.snippet[:60])
    console.print(table)
    console.print(
        "[yellow]Fix: capture the entry-bar value and forward-fill it for the "
        "position lifetime (profit_target_exit_series in "
        "strategy/templates/_runtime.py).[/]"
    )
    console.print()


def _display_recursive(report: RecursiveReport) -> None:
    """Render a recursive analysis scan report."""
    verdict = "PASS" if report.passed else "FAIL"
    color = "green" if report.passed else "red"
    console.print(f"\n[bold {color}]RECURSIVE ANALYSIS: {report.strategy} — {verdict}[/]")
    if report.source_path:
        console.print(f"Source: {report.source_path}")
    if report.indicator_deps:
        console.print(f"Indicator dependencies: {len(report.indicator_deps)} methods analyzed")
    if report.passed:
        console.print("[green]No circular dependencies detected.[/]")
    else:
        for cycle in report.cycles:
            console.print(f"[red]Cycle detected: {' → '.join(cycle)}[/]")
    console.print()


def _display_monte_carlo(res: MonteCarloResult) -> None:
    """Render a Monte Carlo path-level stress result (diagnostic, non-gate)."""
    console.print(f"\n[bold cyan]MC STRESS — {res.method} (n_paths={res.n_paths})[/]")
    console.print("[yellow]Diagnostic only — does not alter the GO/NO-GO gate.[/]")
    table = Table(title=f"Path band ({res.method})")
    table.add_column("Metric", style="cyan")
    table.add_column("Observed", justify="right")
    table.add_column("P5 (worst)", justify="right", style="red")
    table.add_column("P50 (median)", justify="right")
    table.add_column("P95 (best)", justify="right", style="green")
    table.add_row(
        "Max drawdown",
        f"{res.observed_max_drawdown:.4f}",
        f"{res.p5_max_drawdown:.4f}",
        f"{res.p50_max_drawdown:.4f}",
        "—",
    )
    table.add_row(
        "Terminal return",
        f"{res.observed_terminal_return:.4f}",
        f"{res.p5_terminal_return:.4f}",
        "—",
        f"{res.p95_terminal_return:.4f}",
    )
    console.print(table)
    flag = (
        "[red]observed path was unusually lucky (>50% of resampled paths drew down worse)[/]"
        if res.prob_worse_drawdown > 0.5
        else "[green]observed drawdown is within the resampled band[/]"
    )
    console.print(f"P(path worse than observed dd) = {res.prob_worse_drawdown:.3f} — {flag}")
    console.print()


_SIGNAL_QUALITY_ROWS = (
    ("Signal Precision", "precision"),
    ("Signal Recall", "recall"),
    ("Signal Hit Rate", "hit_rate"),
    ("Signal Brier Score", "brier_score"),
    ("Signal OOS Sharpe", "oos_sharpe"),
)


def _format_signal_quality(quality: ResultDict, key: str) -> str:
    value = quality.get(key)
    return "n/a" if value is None else f"{float(value):.3f}"


def _add_signal_quality_rows(table: Table, quality: ResultDict) -> None:
    if not quality:
        return

    for label, key in _SIGNAL_QUALITY_ROWS:
        table.add_row(label, _format_signal_quality(quality, key))


def _signal_quality_summary(result: ResultDict) -> str:
    quality = result.get("signal_quality", {})
    return ", ".join(
        f"{key}={_format_signal_quality(quality, key)}" for _label, key in _SIGNAL_QUALITY_ROWS
    )
