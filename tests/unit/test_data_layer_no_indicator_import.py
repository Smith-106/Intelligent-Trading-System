"""Architecture guard: data/ (L1) must not directly import from indicators/ (L2).

ISS-002 — prevents L1→L2 layer violations. IndicatorEngine must be accessed
via the IndicatorComputer Protocol (quantflow.common.indicator_protocol),
not direct imports from quantflow.indicators.

This test scans every .py file in quantflow/data/ and asserts that none
contain a ``from quantflow.indicators`` import statement. The Protocol
definition itself (indicator_protocol.py) lives in common/, not data/,
so it is not scanned here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Forbidden import pattern: any "from quantflow.indicators..." import
_FORBIDDEN_RE = re.compile(r"^\s*from\s+quantflow\.indicators\b", re.MULTILINE)

# Root of the data layer — adjust if project layout changes
_DATA_LAYER_DIR = Path(__file__).resolve().parents[2] / "quantflow" / "data"


def _scan_forbidden_imports(directory: Path) -> list[tuple[Path, str]]:
    """Return list of (file, offending_line) for any L1→L2 import violations."""
    violations: list[tuple[Path, str]] = []
    if not directory.exists():
        pytest.skip(f"data layer directory not found: {directory}")

    for py_file in directory.rglob("*.py"):
        # Skip test files that may legitimately reference indicators for assertions
        if py_file.name.startswith("test_"):
            continue
        content = py_file.read_text(encoding="utf-8")
        for match in _FORBIDDEN_RE.finditer(content):
            # Extract the full line for a readable error message
            line_start = content.rfind("\n", 0, match.start()) + 1
            line_end = content.find("\n", match.end())
            offending_line = content[line_start : line_end if line_end != -1 else len(content)]
            violations.append((py_file, offending_line.strip()))
    return violations


def test_data_layer_no_indicator_import() -> None:
    """
    Architecture guard: verify data/ layer does not directly import from indicators/.

    This prevents L1→L2 layer violations. IndicatorEngine must be accessed via
    IndicatorComputer Protocol injection, not direct imports.
    """
    violations = _scan_forbidden_imports(_DATA_LAYER_DIR)

    if violations:
        details = "\n".join(
            f"  {path.relative_to(_DATA_LAYER_DIR.parent.parent)}: {line}"
            for path, line in violations
        )
        pytest.fail(
            f"L1→L2 import violations detected in quantflow/data/:\n{details}\n\n"
            "Fix: inject IndicatorComputer via constructor instead of importing "
            "from quantflow.indicators directly. See ISS-002."
        )
