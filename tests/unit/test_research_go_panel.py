"""Unit tests for L6 research GO panel loader (fail-soft export).

Covers TASK-001 (typed snapshot + fail-soft loading of the sealed
performance panel) and TASK-002 (Prometheus gauge push + MonitoringSink
Protocol/Null/Default ``record_research_go_panel`` + CLI import path).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quantflow.common.monitoring_sink import NullMonitoringSink
from quantflow.monitoring import metrics
from quantflow.monitoring.research_go_panel import (
    DEFAULT_RESEARCH_GO_PANEL_PATH,
    REPO_ROOT,
    ResearchGoPanelSnapshot,
    load_research_go_panel,
)
from quantflow.monitoring.sink import DefaultMonitoringSink

SEALED_FINGERPRINT = "e4d2797070a49bc0"


def _sealed_panel_dict() -> dict:
    """Fixture mirroring the sealed SoT values (may embed sealed numbers)."""
    return {
        "as_of": "2026-08-11T13:26:12.007962+00:00",
        "data_fingerprint_aggregate": SEALED_FINGERPRINT,
        "path_semantics": {
            "multi_symbol_replay": "paper_replay virtual book (event path), NOT live",
            "beta_overlay_dual_path": "vectorized research; promotion_eligible=false",
            "parity_note": "parity holds paper<->live only; backtest/vectorized separate",
        },
        "portfolio_modes": {
            "shared_risk_parity": {
                "return_pct": 5.143,
                "sharpe_annualized": 0.2437,
                "max_drawdown_pct": 8.504,
                "orders": 1547,
            }
        },
        "baseline0_gate": {
            "decision": "PAPER-GO",
            "primary_mode": "shared_risk_parity",
            "metrics": {
                "full_return_pct": 5.143,
                "full_sharpe": 0.2437,
                "full_max_dd_pct": 8.504,
                "full_orders": 1547,
            },
        },
    }


@pytest.fixture
def sealed_panel_file(tmp_path: Path) -> Path:
    """Write the fixture panel to a tmp file and return its path."""
    p = tmp_path / "performance_panel.json"
    p.write_text(json.dumps(_sealed_panel_dict()), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# TASK-001 — loader happy path + fail-soft
# ---------------------------------------------------------------------------


def test_default_path_points_to_sealed_sot() -> None:
    assert str(DEFAULT_RESEARCH_GO_PANEL_PATH).replace("\\", "/").endswith(
        "data/paper_replay/perf_verify/performance_panel.json"
    )


def test_load_sealed_panel_happy_path() -> None:
    """The real sealed SoT loads with PAPER-GO / shared_risk_parity mapping."""
    snapshot = load_research_go_panel()
    assert snapshot is not None
    assert snapshot.decision == "PAPER-GO"
    assert snapshot.primary_mode == "shared_risk_parity"
    assert snapshot.data_fingerprint_aggregate == SEALED_FINGERPRINT
    assert snapshot.full_return_pct == pytest.approx(5.143)
    assert snapshot.full_sharpe == pytest.approx(0.2437)
    assert snapshot.full_max_dd_pct == pytest.approx(8.504)
    assert snapshot.full_orders == pytest.approx(1547.0)
    assert snapshot.as_of  # non-empty ISO timestamp
    assert snapshot.promotion_eligible is False
    assert snapshot.loaded_ok is True
    assert "multi_symbol_replay" in snapshot.path_semantics


def test_load_fixture_happy_path(sealed_panel_file: Path) -> None:
    snapshot = load_research_go_panel(sealed_panel_file)
    assert snapshot is not None
    assert snapshot.decision == "PAPER-GO"
    assert snapshot.primary_mode == "shared_risk_parity"
    assert snapshot.promotion_eligible is False
    assert snapshot.to_dict()["decision"] == "PAPER-GO"
    assert snapshot.to_dict()["promotion_eligible"] is False


def test_load_missing_file_returns_none(tmp_path: Path) -> None:
    assert load_research_go_panel(tmp_path / "nope.json") is None


def test_load_invalid_json_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_research_go_panel(p) is None


def test_load_missing_baseline0_gate_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "no_gate.json"
    p.write_text(json.dumps({"as_of": "2026-01-01T00:00:00+00:00"}), encoding="utf-8")
    assert load_research_go_panel(p) is None


def test_load_missing_primary_numbers_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "no_numbers.json"
    payload = _sealed_panel_dict()
    payload["baseline0_gate"]["metrics"] = {"full_return_pct": 5.143}
    del payload["portfolio_modes"]
    p.write_text(json.dumps(payload), encoding="utf-8")
    assert load_research_go_panel(p) is None


def test_promotion_eligible_forced_false(tmp_path: Path) -> None:
    """Even a panel claiming research-promotion eligibility stays False."""
    p = tmp_path / "promo.json"
    payload = _sealed_panel_dict()
    payload["promotion_eligible_any_research"] = True
    p.write_text(json.dumps(payload), encoding="utf-8")
    snapshot = load_research_go_panel(p)
    assert snapshot is not None
    assert snapshot.promotion_eligible is False


def test_gate_metrics_preferred_over_portfolio_modes(tmp_path: Path) -> None:
    """Gate metrics win when both sources carry primary numbers."""
    p = tmp_path / "gate_wins.json"
    payload = _sealed_panel_dict()
    payload["portfolio_modes"]["shared_risk_parity"]["return_pct"] = 999.0
    p.write_text(json.dumps(payload), encoding="utf-8")
    snapshot = load_research_go_panel(p)
    assert snapshot is not None
    assert snapshot.full_return_pct == pytest.approx(5.143)


def test_portfolio_mode_fallback_when_gate_metrics_missing(tmp_path: Path) -> None:
    """portfolio_modes[primary_mode] supplies numbers when gate metrics lack them."""
    p = tmp_path / "fallback.json"
    payload = _sealed_panel_dict()
    del payload["baseline0_gate"]["metrics"]
    p.write_text(json.dumps(payload), encoding="utf-8")
    snapshot = load_research_go_panel(p)
    assert snapshot is not None
    assert snapshot.full_return_pct == pytest.approx(5.143)
    assert snapshot.full_sharpe == pytest.approx(0.2437)
    assert snapshot.full_max_dd_pct == pytest.approx(8.504)
    assert snapshot.full_orders == pytest.approx(1547.0)


def test_path_semantics_copied_only_when_present(tmp_path: Path) -> None:
    p = tmp_path / "no_ps.json"
    payload = _sealed_panel_dict()
    del payload["path_semantics"]
    p.write_text(json.dumps(payload), encoding="utf-8")
    snapshot = load_research_go_panel(p)
    assert snapshot is not None
    assert snapshot.path_semantics == {}


# ---------------------------------------------------------------------------
# TASK-002 — gauge push + sink + CLI
# ---------------------------------------------------------------------------


def _iso_ts_epoch(iso: str) -> float:
    from datetime import UTC, datetime

    ts = datetime.fromisoformat(iso)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.timestamp()


def _fixture_snapshot() -> ResearchGoPanelSnapshot:
    return ResearchGoPanelSnapshot(
        decision="PAPER-GO",
        primary_mode="shared_risk_parity",
        full_return_pct=5.143,
        full_sharpe=0.2437,
        full_max_dd_pct=8.504,
        full_orders=1547.0,
        data_fingerprint_aggregate=SEALED_FINGERPRINT,
        as_of="2026-08-11T13:26:12.007962+00:00",
        path_semantics={"multi_symbol_replay": "paper_replay virtual book"},
    )


def test_metric_names_exist() -> None:
    assert metrics.RESEARCH_GO_DECISION._name == "quantflow_research_go_decision"
    assert metrics.RESEARCH_GO_RETURN_PCT._name == "quantflow_research_go_return_pct"
    assert metrics.RESEARCH_GO_SHARPE._name == "quantflow_research_go_sharpe"
    assert metrics.RESEARCH_GO_MAX_DD_PCT._name == "quantflow_research_go_max_dd_pct"
    assert metrics.RESEARCH_GO_ORDERS._name == "quantflow_research_go_orders"
    assert (
        metrics.RESEARCH_GO_PROMOTION_ELIGIBLE._name
        == "quantflow_research_go_promotion_eligible"
    )
    assert (
        metrics.RESEARCH_GO_AS_OF_TS._name == "quantflow_research_go_as_of_timestamp"
    )


def test_update_research_go_panel_metrics_sets_gauges() -> None:
    snap = _fixture_snapshot()
    metrics.update_research_go_panel_metrics(snap)
    labels = {
        "primary_mode": snap.primary_mode,
        "decision": snap.decision,
        "fingerprint": snap.data_fingerprint_aggregate,
        "promotion_eligible": "false",
    }
    assert metrics.RESEARCH_GO_DECISION.labels(**labels)._value.get() == 1.0
    assert metrics.RESEARCH_GO_RETURN_PCT.labels(**labels)._value.get() == pytest.approx(
        5.143
    )
    assert metrics.RESEARCH_GO_SHARPE.labels(**labels)._value.get() == pytest.approx(
        0.2437
    )
    assert metrics.RESEARCH_GO_MAX_DD_PCT.labels(**labels)._value.get() == pytest.approx(
        8.504
    )
    assert metrics.RESEARCH_GO_ORDERS.labels(**labels)._value.get() == pytest.approx(
        1547.0
    )
    # promotion_eligible is always 0 — research GO export never promotes
    assert (
        metrics.RESEARCH_GO_PROMOTION_ELIGIBLE.labels(**labels)._value.get() == 0.0
    )
    assert metrics.RESEARCH_GO_AS_OF_TS._value.get() == pytest.approx(
        _iso_ts_epoch(snap.as_of)
    )


def test_update_research_go_panel_metrics_none_is_noop() -> None:
    # Must not raise and must not touch the decision gauge family.
    metrics.update_research_go_panel_metrics(None)


def test_decision_gauge_non_paper_go_is_zero() -> None:
    snap = _fixture_snapshot()
    snap.decision = "HOLD"
    metrics.update_research_go_panel_metrics(snap)
    labels = {
        "primary_mode": snap.primary_mode,
        "decision": "HOLD",
        "fingerprint": snap.data_fingerprint_aggregate,
        "promotion_eligible": "false",
    }
    assert metrics.RESEARCH_GO_DECISION.labels(**labels)._value.get() == 0.0


def test_null_sink_record_research_go_panel_is_noop() -> None:
    sink = NullMonitoringSink()
    # No-op must exist (duck-typed callers rely on it) and not raise.
    sink.record_research_go_panel(_fixture_snapshot())
    sink.record_research_go_panel(None)


def test_default_sink_record_research_go_panel_pushes_gauges() -> None:
    sink = DefaultMonitoringSink()
    snap = _fixture_snapshot()
    sink.record_research_go_panel(snap)  # must not raise
    labels = {
        "primary_mode": snap.primary_mode,
        "decision": snap.decision,
        "fingerprint": snap.data_fingerprint_aggregate,
        "promotion_eligible": "false",
    }
    assert metrics.RESEARCH_GO_RETURN_PCT.labels(**labels)._value.get() == pytest.approx(
        5.143
    )


def test_default_sink_record_research_go_panel_none_noop() -> None:
    DefaultMonitoringSink().record_research_go_panel(None)


def test_cli_import_and_run(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Thin CLI loads a panel and prints JSON; missing panel exits non-zero."""
    import scripts.export_research_go_panel as cli

    panel = tmp_path / "panel.json"
    panel.write_text(json.dumps(_sealed_panel_dict()), encoding="utf-8")

    rc = cli.main(["--panel", str(panel)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "PAPER-GO"
    assert out["promotion_eligible"] is False

    rc_missing = cli.main(["--panel", str(tmp_path / "missing.json")])
    assert rc_missing == 2  # non-zero soft code, no traceback
