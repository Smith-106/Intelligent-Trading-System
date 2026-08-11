"""IMP-05 session health + alert taxonomy tests."""

from __future__ import annotations

from quantflow.monitoring.session_health import (
    alert_taxonomy_summary,
    build_session_health,
)


def test_build_session_health_status() -> None:
    snap = build_session_health(
        mode="paper",
        strategy_id="trend",
        up=True,
        bars_processed=100,
        last_bar_age_seconds=5.0,
        open_orders=1,
        push_metrics=True,
    )
    assert snap.status == "healthy"
    d = snap.to_dict()
    assert d["mode"] == "paper"
    assert d["bars_processed"] == 100

    stale = build_session_health(
        mode="paper",
        up=True,
        last_bar_age_seconds=7200,
        push_metrics=False,
    )
    assert stale.status == "stale"

    halted = build_session_health(
        mode="live",
        up=True,
        kill_switch_active=True,
        push_metrics=False,
    )
    assert halted.status == "halted"


def test_alert_taxonomy_has_three_levels_and_routes() -> None:
    tax = alert_taxonomy_summary()
    assert set(tax["levels"]) >= {"info", "warning", "critical"}
    assert len(tax["sample_routes"]) >= 3
    assert tax["routing_matrix_size"] >= 3
    # P0 drawdown must route somewhere
    p0 = next(r for r in tax["sample_routes"] if r["priority"] == "p0_emergency")
    assert len(p0["channels"]) >= 1
