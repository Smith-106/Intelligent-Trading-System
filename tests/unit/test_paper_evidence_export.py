"""T024: paper_evidence export + promote dry-run."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load():
    path = REPO / "scripts" / "paper_evidence_export.py"
    spec = importlib.util.spec_from_file_location("paper_evidence_export", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_evidence_from_streak_short():
    mod = _load()
    led = {
        "days": {
            "2026-08-08": {"date": "2026-08-08", "status": "ok"},
            "2026-08-09": {"date": "2026-08-09", "status": "ok"},
        }
    }
    ev = mod.evidence_from_streak(led, fills=5)
    assert ev["fills"] == 5
    assert ev["paper_days"] >= 2
    assert ev["meets_default_floors"] is False


def test_synthetic_full_meets_floors():
    mod = _load()
    ev = mod.synthetic_full_evidence()
    assert ev["meets_default_floors"] is True
    assert ev["paper_days"] >= 7
    assert ev["fills"] >= 20


def test_dry_run_reject_short(tmp_path: Path):
    mod = _load()
    ev = mod.evidence_from_streak(
        {"days": {"2026-08-09": {"date": "2026-08-09"}}},
        fills=3,
    )
    result = mod.dry_run_promote(ev, registry_dir=tmp_path / "reg")
    assert result["promote"] == "rejected"
    assert "paper readiness" in (result.get("reason") or "").lower()


def test_dry_run_live_with_synthetic(tmp_path: Path):
    mod = _load()
    ev = mod.synthetic_full_evidence(days=10, fills=30)
    result = mod.dry_run_promote(ev, registry_dir=tmp_path / "reg2")
    assert result["promote"] == "live"
    assert result["status"] == "live"
