"""T017: day-session deviation vs Baseline-0."""

from __future__ import annotations

import json
from pathlib import Path

from quantflow.strategy.research.day_deviation import (
    DeviationThresholds,
    evaluate_day_deviation,
    format_alert_message,
    load_baseline_snapshot,
)


def test_health_ok_with_paper_go(tmp_path: Path):
    gate = tmp_path / "gate.json"
    meta = tmp_path / "run_meta.json"
    full = tmp_path / "full.json"
    gate.write_text(
        json.dumps(
            {
                "baseline_id": "Baseline-0",
                "decision": "PAPER-GO",
                "metrics": {
                    "full_return_pct": 5.0,
                    "full_sharpe": 0.2,
                    "full_max_dd_pct": 8.0,
                },
            }
        ),
        encoding="utf-8",
    )
    meta.write_text(
        json.dumps({"start": "2021-01-01", "end": "2026-08-04"}),
        encoding="utf-8",
    )
    full.write_text(
        json.dumps(
            {
                "shared_risk_parity": {
                    "return_pct": 5.0,
                    "sharpe_annualized": 0.2,
                    "max_drawdown_pct": 8.0,
                }
            }
        ),
        encoding="utf-8",
    )
    snap = load_baseline_snapshot(
        repo_root=tmp_path, gate_path=gate, meta_path=meta, full_path=full
    )
    report = evaluate_day_deviation(baseline=snap)
    assert report["status"] == "ok"
    assert report["health_ok"] is True
    assert report["should_alert"] is False


def test_missing_gate_alerts(tmp_path: Path):
    snap = load_baseline_snapshot(
        repo_root=tmp_path,
        gate_path=tmp_path / "missing_gate.json",
        meta_path=tmp_path / "missing_meta.json",
        full_path=tmp_path / "missing_full.json",
    )
    report = evaluate_day_deviation(baseline=snap)
    assert report["status"] == "alert"
    assert report["should_alert"] is True
    assert any(a["code"] == "BASELINE_GATE_MISSING" for a in report["alerts"])


def test_non_go_decision_alerts(tmp_path: Path):
    gate = tmp_path / "gate.json"
    gate.write_text(json.dumps({"decision": "NO-GO", "metrics": {}}), encoding="utf-8")
    meta = tmp_path / "run_meta.json"
    meta.write_text("{}", encoding="utf-8")
    snap = load_baseline_snapshot(
        repo_root=tmp_path,
        gate_path=gate,
        meta_path=meta,
        full_path=tmp_path / "x.json",
    )
    report = evaluate_day_deviation(baseline=snap)
    assert report["status"] == "alert"
    assert any(a["code"] == "BASELINE_NOT_PAPER_GO" for a in report["alerts"])


def test_pnl_band_is_diagnostic_degraded_not_error():
    snap = {
        "baseline_id": "Baseline-0",
        "decision": "PAPER-GO",
        "gate_present": True,
        "meta_present": True,
        "metrics": {
            "full_return_pct": 5.0,
            "full_max_dd_pct": 8.0,
            "full_sharpe": 0.2,
        },
        "path_note": "Path A ≠ Path B",
    }
    report = evaluate_day_deviation(
        baseline=snap,
        day_metrics={"return_pct": 80.0, "max_drawdown_pct": 50.0},
        thresholds=DeviationThresholds(return_band_pp=20.0, max_dd_band_pp=10.0),
    )
    assert report["health_ok"] is True
    assert report["status"] == "degraded"
    assert report["pnl_diagnostic"]["path_a_ne_path_b"] is True
    assert report["pnl_diagnostic"]["comparable"] is False
    assert report["pnl_diagnostic"]["breaches"]["return"] is True


def test_format_alert_message():
    msg = format_alert_message(
        {
            "status": "alert",
            "baseline": {"decision": "NO-GO"},
            "issues": ["baseline decision='NO-GO'"],
        }
    )
    assert "day-deviation" in msg
    assert "NO-GO" in msg


def test_attach_via_paper_day_session_helpers(tmp_path: Path, monkeypatch):
    """Wire-level: _attach_baseline_deviation mutates summary."""
    import importlib.util

    # Build minimal baseline artifacts under tmp as "repo"
    bdir = tmp_path / "data" / "paper_replay" / "baseline0"
    bdir.mkdir(parents=True)
    (bdir / "gate.json").write_text(
        json.dumps(
            {
                "baseline_id": "Baseline-0",
                "decision": "PAPER-GO",
                "metrics": {"full_return_pct": 5.0, "full_max_dd_pct": 8.0},
            }
        ),
        encoding="utf-8",
    )
    (bdir / "run_meta.json").write_text(
        json.dumps({"start": "2021-01-01", "end": "2026-08-04"}),
        encoding="utf-8",
    )
    (bdir / "multi_symbol_replay.json").write_text(
        json.dumps(
            {
                "shared_risk_parity": {
                    "return_pct": 5.0,
                    "max_drawdown_pct": 8.0,
                    "sharpe_annualized": 0.2,
                }
            }
        ),
        encoding="utf-8",
    )

    repo = Path(__file__).resolve().parents[2]
    path = repo / "scripts" / "paper_day_session.py"
    spec = importlib.util.spec_from_file_location("paper_day_session", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Point REPO_ROOT at tmp so load finds our fixtures
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)

    summary: dict = {"status": "ok", "note": "preflight passed", "commands": {}}
    out = mod._attach_baseline_deviation(summary)
    assert "deviation" in out
    assert out["deviation"]["status"] == "ok"
    assert out["baseline_snapshot"]["decision"] == "PAPER-GO"
