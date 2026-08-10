"""B4-OOS independent contract: runner wiring + freeze discipline (not a W-wave)."""

from __future__ import annotations

import json
from pathlib import Path


def test_full_oos_script_exists_and_refuses_b3_entry_equality() -> None:
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts" / "run_baseline4_full_oos.py").read_text(encoding="utf-8")
    assert "B4-OOS-20260810" in script
    assert "baseline4" in script
    assert "baseline3" in script  # refusal logic
    assert "0.0004" in script
    assert "0.001" in script  # B3 reference


def test_results_doc_and_index_mark_keep_b0() -> None:
    root = Path(__file__).resolve().parents[2]
    results = (root / "docs" / "research" / "Candidate-Baseline-4-results.md").read_text(
        encoding="utf-8"
    )
    assert "KEEP_BASELINE_0" in results
    assert "B4-OOS-20260810" in results
    assert "0 fills" in results or "orders=0" in results or "**0**" in results
    idx = (root / "docs" / "research" / "baseline-contract-index.md").read_text(
        encoding="utf-8"
    )
    assert "B4-OOS-20260810" in idx
    assert "KEEP B0" in idx
    # must not claim DRAFT only anymore
    contract = (root / "docs" / "research" / "Candidate-Baseline-4.md").read_text(
        encoding="utf-8"
    )
    assert "FROZEN KEEP_BASELINE_0" in contract


def test_t023_status_doc_honest() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "docs" / "research" / "t023-wall-clock-status.md").read_text(
        encoding="utf-8"
    )
    assert "3" in text
    assert "target_met" in text
    assert "false" in text.lower() or "False" in text
    assert "not a wave" in text.lower() or "not a wave" in text


def test_local_b4_oos_artifacts_if_present_keep() -> None:
    """If operator has local run dir, assert sealed KEEP (optional)."""
    root = Path(__file__).resolve().parents[2]
    adj = root / "data" / "paper_replay" / "baseline4" / "B4-OOS-20260810" / "adjudication.json"
    if not adj.is_file():
        return
    data = json.loads(adj.read_text(encoding="utf-8"))
    assert data.get("keep_baseline0") is True or data.get("verdict") == "KEEP_BASELINE_0"
    assert data.get("upgrade") is False
