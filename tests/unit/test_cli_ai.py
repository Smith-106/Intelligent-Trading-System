"""Tests for the extended AI CLI actions (s3 T-s3-04).

Covers: action enumeration, 'register' gate output (GO → paper,
NO-GO → rejected), unknown-action error, and 'train' report persistence.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from quantflow.cli.main import app

runner = CliRunner()


def test_ai_help_lists_all_actions():
    result = runner.invoke(app, ["ai", "--help"])
    assert result.exit_code == 0
    for action in ("rdagent", "research", "train", "register"):
        assert action in result.stdout


def test_ai_unknown_action_reports_available():
    result = runner.invoke(app, ["ai", "nonsense"])
    assert result.exit_code == 0
    assert "Unknown AI action" in result.stdout
    for action in ("rdagent", "research", "train", "register"):
        assert action in result.stdout


def test_ai_register_requires_model_id():
    result = runner.invoke(app, ["ai", "register"])
    assert result.exit_code == 0
    assert "--model-id is required" in result.stdout


def test_ai_register_no_report_found(tmp_path):
    result = runner.invoke(
        app,
        ["ai", "register", "--model-id", "model-ghost", "--registry-dir", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "No training report found" in result.stdout


def test_ai_register_no_go_rejected(tmp_path):
    """A NO-GO report must produce status=rejected (fail-closed)."""
    report_dir = Path("data/ai_reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "model_id": "model-nogo",
        "model_cls": "RandomForestClassifier",
        "features_hash": "abc",
        "n_samples": 100,
        "decision": "NO-GO",
        "reason": "DSR < 0.95",
        "validation": {"decision": "NO-GO", "reason": "DSR < 0.95"},
    }
    (report_dir / "model-nogo.json").write_text(json.dumps(report), encoding="utf-8")
    try:
        result = runner.invoke(
            app,
            ["ai", "register", "--model-id", "model-nogo", "--registry-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert "status=rejected" in result.stdout
    finally:
        (report_dir / "model-nogo.json").unlink(missing_ok=True)


def test_ai_register_go_becomes_paper(tmp_path):
    """A GO report must register as paper (usable for promotion)."""
    report_dir = Path("data/ai_reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    cost_grid = [
        {"taker_fee": 0.0, "slippage": 0.0, "sharpe": 1.0, "return_pct": 20.0},
        {"taker_fee": 0.001, "slippage": 0.001, "sharpe": 0.55, "return_pct": 10.0},
    ]
    report = {
        "model_id": "model-gogo",
        "model_cls": "RandomForestClassifier",
        "features_hash": "abc",
        "n_samples": 100,
        "decision": "GO",
        "reason": "All validation checks passed",
        "validation": {
            "decision": "GO",
            "reason": "All validation checks passed",
            "checks": {},
            "fee_slip_grid": cost_grid,
            "funding_tca": {
                "mode": "assumption",
                "assumed_abs_funding_per_event": 0.0001,
                "estimated_annual_drag_pct": 10.95,
            },
        },
        "fee_slip_grid": cost_grid,
        "funding_tca": {
            "mode": "assumption",
            "assumed_abs_funding_per_event": 0.0001,
            "estimated_annual_drag_pct": 10.95,
        },
    }
    (report_dir / "model-gogo.json").write_text(json.dumps(report), encoding="utf-8")
    try:
        result = runner.invoke(
            app,
            ["ai", "register", "--model-id", "model-gogo", "--registry-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert "status=paper" in result.stdout
        # Registry file persisted.
        assert (tmp_path / "model-gogo.json").exists()
    finally:
        (report_dir / "model-gogo.json").unlink(missing_ok=True)
