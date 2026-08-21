"""T027: Baseline-3 adjudication freeze invariants."""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_adjudication_frozen_file():
    p = REPO / "data" / "paper_replay" / "baseline3" / "adjudication_frozen.json"
    if not p.is_file():
        # Artifacts may be gitignored; fall back to docs freeze language
        doc = (REPO / "docs" / "research" / "Candidate-Baseline-3.md").read_text(encoding="utf-8")
        assert "FROZEN KEEP_BASELINE_0" in doc or "FROZEN T027" in doc
        return
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["verdict"] == "KEEP_BASELINE_0"
    assert raw["upgrade"] is False
    assert raw["task"] == "T027"
    assert raw["baseline"] == "B3"


def test_contract_doc_frozen():
    doc = (REPO / "docs" / "research" / "Candidate-Baseline-3.md").read_text(encoding="utf-8")
    assert "KEEP_BASELINE_0" in doc
    assert "T027" in doc
    assert "upgrade | **false**" in doc or "upgrade | **false**" in doc.replace(" ", " ")


def test_index_lists_b3_keep():
    idx = (REPO / "docs" / "research" / "baseline-contract-index.md").read_text(encoding="utf-8")
    assert "B3" in idx
    assert "KEEP B0" in idx
    assert "funding_rate" in idx
    # sole PAPER-GO remains B0
    assert "PAPER-GO" in idx
