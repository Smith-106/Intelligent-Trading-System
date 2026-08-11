"""One-shot causal / anti-lookahead preflight for dual-path research OS.

Combines static ``generate_signals`` look-ahead scan + negative-shift AST.
Optional extra source blobs can be scanned without strategy instances.
"""

from __future__ import annotations

import inspect
import textwrap
from dataclasses import asdict, dataclass, field
from typing import Any

from quantflow.indicators.causal import (
    ShiftFinding,
    scan_callable_for_negative_shift,
    scan_source_for_negative_shift,
)
from quantflow.strategy.base import StrategyBase
from quantflow.strategy.validation.lookahead import LookaheadReport, scan_strategy


@dataclass
class CausalPreflightReport:
    """Aggregated causal preflight result."""

    passed: bool
    findings: list[dict[str, Any]] = field(default_factory=list)
    severity_counts: dict[str, int] = field(default_factory=dict)
    lookahead: dict[str, Any] | None = None
    negative_shifts: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        if self.passed:
            return "CAUSAL PREFLIGHT: PASS"
        n = self.severity_counts.get("high", 0)
        return f"CAUSAL PREFLIGHT: FAIL — {len(self.findings)} finding(s) ({n} high)"


def _shift_to_dict(hit: ShiftFinding) -> dict[str, Any]:
    return {
        "where": hit.where,
        "line": hit.line,
        "snippet": hit.snippet,
        "detail": hit.detail,
    }


def _bump(counts: dict[str, int], severity: str) -> None:
    counts[severity] = int(counts.get(severity, 0)) + 1


def _instantiate(strategy: StrategyBase | type) -> StrategyBase:
    if isinstance(strategy, type):
        try:
            return strategy(None)  # type: ignore[call-arg, return-value]
        except Exception:
            return strategy()  # type: ignore[misc, call-arg, return-value]
    return strategy


def run_causal_preflight(
    strategy: StrategyBase | type | None = None,
    *,
    extra_sources: list[tuple[str, str]] | None = None,
) -> CausalPreflightReport:
    """Run static causal preflight (no market data required).

    Parameters
    ----------
    strategy:
        Strategy instance or class with ``generate_signals``.
    extra_sources:
        Optional ``(label, source_text)`` pairs for additional AST scans.
    """
    findings: list[dict[str, Any]] = []
    neg: list[dict[str, Any]] = []
    severity_counts: dict[str, int] = {"high": 0, "medium": 0, "low": 0, "info": 0}
    lookahead_dict: dict[str, Any] | None = None
    notes: list[str] = []

    if strategy is None and not extra_sources:
        return CausalPreflightReport(
            passed=False,
            findings=[
                {
                    "source": "input",
                    "detail": "no strategy or extra_sources provided",
                    "severity": "high",
                }
            ],
            severity_counts={"high": 1, "medium": 0, "low": 0, "info": 0},
            notes=["empty preflight input"],
        )

    if strategy is not None:
        inst = _instantiate(strategy)
        la: LookaheadReport = scan_strategy(inst)
        lookahead_dict = {
            "strategy": la.strategy,
            "passed": bool(la.passed),
            "scanned_methods": list(la.scanned_methods),
            "source_path": la.source_path,
            "findings": [
                {
                    "method": f.method,
                    "pattern": f.pattern,
                    "line": f.line,
                    "severity": f.severity,
                    "snippet": f.snippet,
                    "note": f.note,
                }
                for f in la.findings
            ],
        }
        for f in la.findings:
            sev = f.severity if f.severity in severity_counts else "medium"
            findings.append(
                {
                    "source": "lookahead",
                    "detail": {
                        "method": f.method,
                        "pattern": f.pattern,
                        "line": f.line,
                        "snippet": f.snippet,
                        "note": f.note,
                    },
                    "severity": sev,
                }
            )
            _bump(severity_counts, sev)

        # Explicit negative-shift scan on generate_signals (and related callables)
        for hit in scan_callable_for_negative_shift(
            inst.generate_signals, where="generate_signals"
        ):
            item = _shift_to_dict(hit)
            neg.append(item)
            findings.append(
                {"source": "negative_shift", "detail": item, "severity": "high"}
            )
            _bump(severity_counts, "high")

        # Also scan full class source when available (catches helpers)
        try:
            cls_src = textwrap.dedent(inspect.getsource(type(inst)))
            for hit in scan_source_for_negative_shift(
                cls_src, where=type(inst).__name__
            ):
                # Dedup by line+snippet
                item = _shift_to_dict(hit)
                key = (item["line"], item["snippet"])
                if any((n.get("line"), n.get("snippet")) == key for n in neg):
                    continue
                neg.append(item)
                findings.append(
                    {"source": "negative_shift", "detail": item, "severity": "high"}
                )
                _bump(severity_counts, "high")
        except (OSError, TypeError) as exc:
            notes.append(f"class source scan skipped: {exc}")

    for label, source in extra_sources or []:
        for hit in scan_source_for_negative_shift(source, where=label):
            item = _shift_to_dict(hit)
            neg.append(item)
            findings.append(
                {"source": "negative_shift", "detail": item, "severity": "high"}
            )
            _bump(severity_counts, "high")

    passed = severity_counts.get("high", 0) == 0
    return CausalPreflightReport(
        passed=passed,
        findings=findings,
        severity_counts=severity_counts,
        lookahead=lookahead_dict,
        negative_shifts=neg,
        notes=notes,
    )
