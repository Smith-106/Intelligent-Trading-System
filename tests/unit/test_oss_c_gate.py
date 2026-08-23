"""T020: open-source C readiness gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load():
    path = REPO / "scripts" / "oss_c_gate.py"
    spec = importlib.util.spec_from_file_location("oss_c_gate", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_required_docs_present():
    mod = _load()
    r = mod.check_required_docs(REPO)
    assert r["ok"] is True, r.get("missing")


def test_gitignore_hard_rules():
    mod = _load()
    r = mod.check_gitignore(REPO)
    assert r["ok"] is True, r.get("hard_missing")


def test_secret_scan_clean_on_fixture(tmp_path: Path):
    mod = _load()
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
    r = mod.secret_scan(tmp_path)
    assert r["ok"] is True
    assert r["hits"] == []


def test_secret_scan_hits_private_key(tmp_path: Path):
    mod = _load()
    # Build marker without embedding a full PEM block in the test source tree scan path.
    pem = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIE\n"
    (tmp_path / "leak.md").write_text(pem, encoding="utf-8")
    r = mod.secret_scan(tmp_path)
    assert r["ok"] is False
    assert any(h["rule"] == "private_key_pem" for h in r["hits"])


@pytest.mark.slow
def test_run_gate_quick_structure():
    # REV-018: run_gate scans the whole repo (docs/gitignore/secrets/CI);
    # measured at ~8.5s it dominates the unit suite. Contract still runs,
    # just out of the fast lane.
    mod = _load()
    report = mod.run_gate(quick=True)
    assert report["kind"] == "oss_c_gate"
    assert "visibility_note" in report
    assert "checks" in report
    # Docs we just added should make docs check pass
    assert report["checks"]["docs"]["ok"] is True
