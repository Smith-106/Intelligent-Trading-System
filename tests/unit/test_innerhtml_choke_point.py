"""M4 guard: metricCard must escape its string/label branches, and the
setHTML choke point must remain the single audit face for innerHTML assignment.

The original M4 gap (design-guide.md / diagnosis.md): metricCard escaped the
``else`` branch via ``escapeHtml(String(value))`` but the string branch
(``localizeInlineText(value, value)``) and the label interpolation were NOT
escaped — a backend-supplied metric value containing ``<`` would render as
raw HTML (latent XSS sink across the 96 innerHTML sites).

This test freezes the fix so a future commit that drops the ``escapeHtml``
wrap on the string/label branch is caught at CI time. It also asserts the
``setHTML`` choke-point helper exists as the single audit face (mirrors the
``validate_symbol`` single-audit-face discipline, specs[coding]).
"""

from __future__ import annotations

import re
from pathlib import Path

APP_JS = Path(__file__).resolve().parents[2] / "quantflow" / "web" / "static" / "app.js"


def _read() -> str:
    return APP_JS.read_text(encoding="utf-8")


def test_sethtml_choke_point_exists() -> None:
    """The setHTML helper must exist as the single audit face for innerHTML
    assignment (M4). Its body is the one place a raw ``.innerHTML =`` is
    permitted; the static guard below strips it before scanning.
    """
    src = _read()
    assert re.search(r"\bfunction\s+setHTML\s*\(", src), (
        "setHTML choke-point helper missing in app.js — M4 requires it as the "
        "single audit face for innerHTML assignment."
    )


def test_metric_card_escapes_string_and_label_branches() -> None:
    """metricCard must wrap the string branch and the label interpolation in
    escapeHtml. This is the confirmed XSS sink (design-guide M4). A future
    commit reverting either wrap reopens the surface for any backend metric
    value containing ``<``.
    """
    src = _read()
    m = re.search(r"function metricCard\([^)]*\)\s*\{(?P<body>.*?)\n\}", src, re.DOTALL)
    assert m is not None, "metricCard function not found in app.js"
    body = m.group("body")
    # String branch: display = escapeHtml(localizeInlineText(...))
    assert re.search(r"display\s*=\s*escapeHtml\(\s*localizeInlineText\(", body), (
        "metricCard string branch must escape via escapeHtml(localizeInlineText(...)) — "
        "M4 fix reverted (string branch unescaped = XSS sink)."
    )
    # Label: safeLabel = escapeHtml(localizeInlineText(label, label))
    assert re.search(r"safeLabel\s*=\s*escapeHtml\(\s*localizeInlineText\(", body), (
        "metricCard label must escape via escapeHtml(localizeInlineText(label, label)) — "
        "M4 fix reverted (label unescaped = XSS sink)."
    )
    assert "safeLabel" in body and "safeLabel}" in body.replace(" ", ""), (
        "metricCard must interpolate safeLabel (escaped) into the label span."
    )
