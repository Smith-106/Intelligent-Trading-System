"""ISS-019 guard: the web layer must not call the unsafe resolve_config_path.

``resolve_config_path`` (CLI/internal) accepts absolute and ``..`` paths; the
web layer must confine request-supplied config paths via
``resolve_config_path_safe`` only. This test greps ``quantflow/web/`` so a
future commit that adds a ``resolve_config_path(...)`` call site (instead of
the safe variant) is caught at CI time, not after a path-traversal regression.
"""

from __future__ import annotations

import re
from pathlib import Path


def _web_python_files() -> list[Path]:
    root = Path(__file__).resolve().parents[2] / "quantflow" / "web"
    return sorted(root.rglob("*.py"))


def test_web_layer_has_no_unsafe_resolve_config_path_call() -> None:
    """No ``quantflow/web/`` module may call resolve_config_path(...) (the
    CLI/unsafe variant). Only resolve_config_path_safe is permitted for
    request-supplied paths. The name itself is a footgun (ISS-019).
    """
    # Match "resolve_config_path(" but NOT "resolve_config_path_safe(" and not
    # the safe variant as a substring. Also allow the name in comments / the
    # back-compat re-export block (which only imports, never calls).
    unsafe_call = re.compile(r"\bresolve_config_path\s*\(")
    safe_call = re.compile(r"\bresolve_config_path_safe\s*\(")
    violations: list[str] = []
    for path in _web_python_files():
        text = path.read_text(encoding="utf-8")
        # Strip safe calls first so their "(" doesn't masquerade as unsafe.
        text_without_safe = safe_call.sub("resolve_config_path_safe_CALLED(", text)
        for m in unsafe_call.finditer(text_without_safe):
            line_no = text[: m.start()].count("\n") + 1
            violations.append(f"{path.name}:{line_no}")
    assert not violations, (
        "quantflow/web/ must not call resolve_config_path(...) (CLI/unsafe). "
        "Use resolve_config_path_safe for request-supplied paths. Violations: "
        + ", ".join(violations)
    )
