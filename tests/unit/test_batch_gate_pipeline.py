"""T015: batch gate pipeline dry-run + fail-closed aggregation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load():
    path = REPO / "scripts" / "batch_gate_pipeline.py"
    spec = importlib.util.spec_from_file_location("batch_gate_pipeline", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_dry_run_all_pass_schema():
    mod = _load()
    payload = mod.run_batch(
        ["trend_following", "mean_reversion"],
        dry_run=True,
    )
    assert payload["summary"]["overall"] == "pass"
    assert payload["summary"]["pass"] == 2
    assert all(c["status"] == "pass" for c in payload["candidates"])
    assert payload["funding_tca_summary"]["mode"] in ("assumption", "hybrid", "measured")


def test_evaluate_candidate_rejects_without_funding(monkeypatch):
    mod = _load()
    # Force empty funding by patching builder path inside evaluate via dry_run false
    # with broken grid is heavy; unit-test assert path via evaluate dry_run + empty funding.
    import pandas as pd

    bad_funding: dict = {}  # missing quantitative fields
    row = mod.evaluate_candidate(
        "trend_following",
        pd.DataFrame(),
        funding_tca=bad_funding,
        dry_run=True,
    )
    assert row["status"] == "rejected"
    assert any("funding" in r.lower() for r in row["reasons"])


def test_cli_dry_run(tmp_path, monkeypatch):
    mod = _load()
    out = tmp_path / "batch.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "batch_gate_pipeline.py",
            "--dry-run",
            "--strategies",
            "trend_following",
            "--out",
            str(out),
        ],
    )
    rc = mod.main()
    assert rc == 0
    assert out.is_file()
    assert out.with_suffix(".md").is_file()
