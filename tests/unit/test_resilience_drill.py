"""T021: resilience drill (corrupt checkpoint + drift alert closed loop)."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load():
    path = REPO / "scripts" / "resilience_drill.py"
    spec = importlib.util.spec_from_file_location("resilience_drill", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_resilience_drill_all_pass():
    mod = _load()
    report = asyncio.run(mod.run_drill())
    assert report["summary"]["overall"] == "pass"
    assert report["summary"]["pass"] == 4
    ids = {s["id"] for s in report["scenarios"]}
    assert "A_corrupt_checkpoint" in ids
    assert "C_drift_critical_alert" in ids


def test_handle_significant_drift_no_stale_todo():
    """T021: stale TODO removed; alert owned by _emit_drift_alert."""
    src = (REPO / "quantflow" / "reconciliation" / "engine.py").read_text(encoding="utf-8")
    assert "TODO: Trigger alerts" not in src
    assert "_emit_drift_alert" in src
