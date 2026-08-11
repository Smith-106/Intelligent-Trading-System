"""Regression lock: dual-path reports must not emit combined_score decisions."""

from __future__ import annotations

import re
from pathlib import Path

from quantflow.strategy.research.dual_path_report import (
    assert_no_combined_score,
    build_dual_path_report,
)

ROOT = Path(__file__).resolve().parents[2]

# Assignment / dict-key patterns that would inject a forbidden decision field
_BAD_PATTERNS = [
    re.compile(r"""["']combined_score["']\s*:"""),
    re.compile(r"""["']composite_score["']\s*:"""),
    re.compile(r"""\bcombined_score\s*="""),
    re.compile(r"""\bcomposite_score\s*="""),
    re.compile(r"""\[["']combined_score["']\]\s*="""),
    re.compile(r"""\[["']composite_score["']\]\s*="""),
]

MODULES = [
    ROOT / "quantflow" / "strategy" / "research" / "dual_path_report.py",
    ROOT / "quantflow" / "strategy" / "research" / "dual_path_profiles.py",
    ROOT / "quantflow" / "strategy" / "research" / "n_trials_budget.py",
    ROOT / "quantflow" / "strategy" / "research" / "tpsl_validation_report.py",
    ROOT / "scripts" / "run_dual_path_report.py",
    ROOT / "scripts" / "run_dual_path_research_os.py",
]


def test_source_has_no_forbidden_decision_assignments() -> None:
    for path in MODULES:
        assert path.is_file(), f"missing {path}"
        text = path.read_text(encoding="utf-8")
        for pat in _BAD_PATTERNS:
            m = pat.search(text)
            assert m is None, f"{path.name} has forbidden pattern {pat.pattern}: {m.group(0)!r}"


def test_runtime_report_rejects_combined_score() -> None:
    r = build_dual_path_report(
        path_a={"metrics": {"excess_return_pct": 1.0}},
        path_b={"metrics": {"excess_return_pct": 2.0}},
    )
    d = r.to_dict()
    assert "combined_score" not in d
    assert "composite_score" not in d
    assert_no_combined_score(d)
