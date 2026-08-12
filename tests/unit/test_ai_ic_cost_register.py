"""P1 T006: IC floor + cost fidelity on register path."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from quantflow.cli.main import app
from quantflow.strategy.model_registry import STATUS_PAPER, STATUS_REJECTED, ModelRegistry
from quantflow.strategy.validation.cost_fidelity import (
    attach_cost_fidelity,
    build_funding_tca,
)


def _grid() -> list[dict]:
    return [
        {"taker_fee": 0.0, "slippage": 0.0, "sharpe": 1.0, "return_pct": 20.0},
        {"taker_fee": 0.001, "slippage": 0.001, "sharpe": 0.55, "return_pct": 10.0},
    ]


def _funding() -> dict:
    return build_funding_tca(mode="assumption")


def test_register_rejects_low_ic(tmp_path: Path):
    report_dir = Path("data/ai_reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    mid = "model-lowic"
    payload = {
        "model_id": mid,
        "model_cls": "RF",
        "features_hash": "h",
        "decision": "GO",
        "validation": attach_cost_fidelity(
            {
                "decision": "GO",
                "execution_path": "paper_replay",
                "data_fingerprint": {"aggregate": "test-ai-ic-low"},
            },
            fee_slip_grid=_grid(),
            funding_tca=_funding(),
        ),
        "fee_slip_grid": _grid(),
        "funding_tca": _funding(),
        "execution_path": "paper_replay",
        "data_fingerprint": {"aggregate": "test-ai-ic-low"},
        "ic_metrics": {"mean_ic": 0.01, "threshold": 0.03},
    }
    path = report_dir / f"{mid}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["ai", "register", "--model-id", mid, "--registry-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert "status=rejected" in result.stdout or "NO-GO" in result.stdout
        entry = ModelRegistry(tmp_path).get(mid)
        assert entry is not None
        assert entry["status"] == STATUS_REJECTED
        assert "IC" in entry.get("reason", "")
    finally:
        path.unlink(missing_ok=True)


def test_register_accepts_go_with_cost_and_ic(tmp_path: Path):
    report_dir = Path("data/ai_reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    mid = "model-okic"
    payload = {
        "model_id": mid,
        "model_cls": "RF",
        "features_hash": "h",
        "decision": "GO",
        "validation": attach_cost_fidelity(
            {
                "decision": "GO",
                "execution_path": "paper_replay",
                "data_fingerprint": {"aggregate": "test-ai-ic-ok"},
            },
            fee_slip_grid=_grid(),
            funding_tca=_funding(),
        ),
        "fee_slip_grid": _grid(),
        "funding_tca": _funding(),
        "execution_path": "paper_replay",
        "data_fingerprint": {"aggregate": "test-ai-ic-ok"},
        "ic_metrics": {"mean_ic": 0.05, "threshold": 0.03},
    }
    path = report_dir / f"{mid}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["ai", "register", "--model-id", mid, "--registry-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert "status=paper" in result.stdout
        assert ModelRegistry(tmp_path).get(mid)["status"] == STATUS_PAPER
    finally:
        path.unlink(missing_ok=True)
