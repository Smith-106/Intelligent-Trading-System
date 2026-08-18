"""Coverage completion for quantflow/monitoring (round 5).

Targets the remaining uncovered lines/branches (baseline):
- sink.py              60%  (start with channels, record_* seams, strategy pnl,
                             allocation, research-go fail-soft, send_alert paths)
- research_go_panel.py 87%  (coerce failures, fallback modes, relative path,
                             non-dict payload, missing decision, path_semantics)
- session_health.py    90%  (to_dict timestamp fill, down/degraded status)
- metrics.py           96%  (research-go as_of empty/naive/invalid)
- alerts.py            96%  (send_routed explicit level, line/webhook sends)

No network / no real IO — every external seam is mocked.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from quantflow.monitoring import sink as sink_mod
from quantflow.monitoring.alerts import (
    AlertCategory,
    AlertLevel,
    AlertManager,
    AlertPriority,
)
from quantflow.monitoring.metrics import update_research_go_panel_metrics
from quantflow.monitoring.research_go_panel import (
    ResearchGoPanelSnapshot,
    _coerce_float,
    _extract_primary_numbers,
    load_research_go_panel,
)
from quantflow.monitoring.session_health import SessionHealthSnapshot, build_session_health


# --------------------------------------------------------------------------- #
# sink.py
# --------------------------------------------------------------------------- #


def test_sink_start_wires_alert_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sink_mod, "start_metrics_server", lambda port: None)
    channel = SimpleNamespace(token="tok", chat_id="cid")
    config = SimpleNamespace(
        monitoring=SimpleNamespace(prometheus_port=9999, alert_channels=[channel])
    )
    sink = sink_mod.DefaultMonitoringSink()
    sink.start(config)
    assert sink._alert_mgr is not None


def test_sink_start_without_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sink_mod, "start_metrics_server", lambda port: None)
    config = SimpleNamespace(monitoring=SimpleNamespace(prometheus_port=9999, alert_channels=[]))
    sink = sink_mod.DefaultMonitoringSink()
    sink.start(config)
    assert sink._alert_mgr is None


def test_sink_record_seams() -> None:
    """Exercise every remaining record_* one-liner (no raise)."""
    sink = sink_mod.DefaultMonitoringSink()
    sink.record_signal("s1", "long")  # 81
    sink.record_signal_latency("s1", 0.01)  # 90
    sink.record_risk_event("exchange_circuit_open", "emergency")  # 109
    sink.record_kill_switch_activation("manual")  # 114
    sink.record_kill_switch_step_failure("cancel_orders")  # 118
    sink.record_gateway_connected("okx", True)  # 136
    sink.record_gateway_disconnect("okx", "timeout")  # 141
    sink.record_gateway_reconnect("okx", True)  # 146
    sink.record_order_timed_out("BTC/USDT", "buy")  # 151
    sink.record_strategy_pnl("s1", 12.5)  # 157 (no budget)
    sink.record_strategy_pnl("s2", -3.0, budget_utilization=0.42)  # 158-159
    sink.record_portfolio_allocation({"s1": 0.6, "s2": 0.4})  # 164-165


def test_sink_record_research_go_panel_fail_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(snapshot: Any) -> None:
        raise RuntimeError("panel boom")

    monkeypatch.setattr(sink_mod, "update_research_go_panel_metrics", _boom)
    sink = sink_mod.DefaultMonitoringSink()
    sink.record_research_go_panel(SimpleNamespace())  # exception swallowed (176-177)


@pytest.mark.asyncio
async def test_sink_send_alert_without_and_with_manager() -> None:
    sink = sink_mod.DefaultMonitoringSink()
    assert await sink.send_alert("hello") == {}  # 185-186

    class _FakeAlertMgr:
        async def send(self, message: str, level: Any, extra: dict[str, Any] | None) -> dict[str, bool]:
            return {"telegram": True}

    sink._alert_mgr = _FakeAlertMgr()  # type: ignore[assignment]
    result = await sink.send_alert("hello", level="info", extra={"a": 1})  # 187-191
    assert result == {"telegram": True}
    # unknown level falls back to WARNING via _LEVEL_MAP default
    assert await sink.send_alert("hi", level="bogus") == {"telegram": True}


def test_sink_factory() -> None:
    assert isinstance(sink_mod.create_default_sink(), sink_mod.DefaultMonitoringSink)


# --------------------------------------------------------------------------- #
# research_go_panel.py
# --------------------------------------------------------------------------- #


def test_coerce_float_none_and_invalid() -> None:
    assert _coerce_float("k", None) is None  # 88
    assert _coerce_float("k", "not-a-number") is None  # 91-92
    assert _coerce_float("k", "1.5") == 1.5


def test_extract_primary_numbers_gate_bad_value_falls_back() -> None:
    """A bad gate value (111->108) is backfilled from the mode block (118 continue)."""
    gate_metrics = {
        "full_return_pct": 12.5,
        "full_sharpe": "bad",
        "full_max_dd_pct": -8.0,
        "full_orders": 120,
    }
    modes = {"risk_parity": {"sharpe_annualized": 1.4}}
    numbers = _extract_primary_numbers(gate_metrics, modes, "risk_parity")
    assert numbers is not None
    assert numbers["full_sharpe"] == 1.4
    assert numbers["full_return_pct"] == 12.5


def test_extract_primary_numbers_mode_block_missing_and_invalid() -> None:
    # primary_mode absent from portfolio_modes → not a dict → 115->123 → None
    assert _extract_primary_numbers(None, {"risk_parity": "nope"}, "risk_parity") is None
    # fallback values invalid → 121->116 → never fills → None
    modes = {
        "risk_parity": {
            "return_pct": "bad",
            "sharpe_annualized": "bad",
            "max_drawdown_pct": "bad",
            "orders": "bad",
        }
    }
    assert _extract_primary_numbers(None, modes, "risk_parity") is None


def _panel_payload() -> dict[str, Any]:
    return {
        "baseline0_gate": {
            "decision": "PAPER-GO",
            "primary_mode": "risk_parity",
            "metrics": {
                "full_return_pct": 12.5,
                "full_sharpe": 1.4,
                "full_max_dd_pct": -8.0,
                "full_orders": 120,
            },
        },
        "portfolio_modes": {"risk_parity": {}},
        "data_fingerprint_aggregate": "fp-abc",
        "as_of": "2024-01-01T00:00:00Z",
        "path_semantics": {"multi_symbol_replay": True},
    }


def test_load_panel_relative_path_resolves_to_repo_root(tmp_path: pytest.TempPathFactory) -> None:
    # Relative path is resolved against REPO_ROOT (141) and fails is_file (no write).
    assert load_research_go_panel("no/such/panel.json") is None


def test_load_panel_non_dict_payload(tmp_path: pytest.TempPathFactory) -> None:
    p = tmp_path / "panel.json"
    p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert load_research_go_panel(p) is None  # 158-161


def test_load_panel_missing_decision_primary_mode(tmp_path: pytest.TempPathFactory) -> None:
    p = tmp_path / "panel.json"
    p.write_text(json.dumps({"baseline0_gate": {"metrics": {}}}), encoding="utf-8")
    assert load_research_go_panel(p) is None  # 174-178


def test_load_panel_path_semantics_keys_missing(tmp_path: pytest.TempPathFactory) -> None:
    payload = _panel_payload()
    payload["path_semantics"] = {"other_key": 1}  # none of the tracked keys → 196->195
    p = tmp_path / "panel.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    snap = load_research_go_panel(p)
    assert snap is not None
    assert snap.path_semantics == {}


def test_snapshot_to_dict() -> None:
    snap = ResearchGoPanelSnapshot(
        decision="PAPER-GO",
        primary_mode="risk_parity",
        full_return_pct=1.0,
        full_sharpe=2.0,
        full_max_dd_pct=-1.0,
        full_orders=3.0,
        data_fingerprint_aggregate="fp",
        as_of="",
    )
    d = snap.to_dict()
    assert d["decision"] == "PAPER-GO"
    assert d["promotion_eligible"] is False


# --------------------------------------------------------------------------- #
# session_health.py
# --------------------------------------------------------------------------- #


def test_session_health_to_dict_fills_generated_at() -> None:
    snap = SessionHealthSnapshot(mode="paper", strategy_id="s1", up=True)
    d = snap.to_dict()
    assert d["generated_at"]  # 43


def test_session_health_status_down() -> None:
    assert SessionHealthSnapshot(mode="paper", strategy_id="s", up=False).status == "down"  # 51


def test_session_health_status_degraded() -> None:
    snap = SessionHealthSnapshot(
        mode="paper", strategy_id="s", up=True, gateway_connected=False
    )
    assert snap.status == "degraded"  # 55


def test_build_session_health_no_push_metrics() -> None:
    snap = build_session_health(
        mode="paper", strategy_id="s", push_metrics=False, notes=["note"]
    )
    assert snap.notes == ["note"]
    assert snap.generated_at


# --------------------------------------------------------------------------- #
# metrics.py
# --------------------------------------------------------------------------- #


def _snap(as_of: str) -> ResearchGoPanelSnapshot:
    return ResearchGoPanelSnapshot(
        decision="PAPER-GO",
        primary_mode="risk_parity",
        full_return_pct=12.5,
        full_sharpe=1.4,
        full_max_dd_pct=-8.0,
        full_orders=120.0,
        data_fingerprint_aggregate="fp",
        as_of=as_of,
    )


def test_update_research_go_metrics_empty_as_of() -> None:
    update_research_go_panel_metrics(_snap(""))  # 381->exit False branch


def test_update_research_go_metrics_naive_as_of() -> None:
    update_research_go_panel_metrics(_snap("2024-01-01T00:00:00"))  # 385 tz replace


def test_update_research_go_metrics_invalid_as_of() -> None:
    update_research_go_panel_metrics(_snap("not-a-date"))  # 387-388 ValueError


def test_update_research_go_metrics_none() -> None:
    update_research_go_panel_metrics(None)  # fail-soft no-op


# --------------------------------------------------------------------------- #
# alerts.py
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_send_routed_with_explicit_level_no_channels() -> None:
    mgr = AlertManager()
    result = await mgr.send_routed(
        "msg",
        AlertCategory.RECONCILIATION_DRIFT,
        AlertPriority.P0_EMERGENCY,
        level=AlertLevel.INFO,  # explicit → skips inference (296->305)
    )
    assert result == {}  # telegram token missing → 316->318


@pytest.mark.asyncio
async def test_send_routed_line_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mgr = AlertManager(line_token="lt", line_user_id="uid")
    calls: list[tuple[str, AlertLevel]] = []

    async def fake_line(message: str, level: AlertLevel) -> bool:
        calls.append((message, level))
        return True

    monkeypatch.setattr(mgr, "_send_line", fake_line)
    result = await mgr.send_routed(
        "drawdown!",
        AlertCategory.DRAWDOWN_BREACH,
        AlertPriority.P0_EMERGENCY,  # routes to telegram+line+webhook
    )
    assert result == {"line": True}  # 319
    assert calls[0][1] == AlertLevel.CRITICAL  # inferred from P0


@pytest.mark.asyncio
async def test_send_routed_webhook_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mgr = AlertManager(webhook_url="https://hooks.example.com/qf")
    calls: list[tuple[str, AlertLevel]] = []

    async def fake_webhook(message: str, level: AlertLevel, extra: dict[str, Any] | None) -> bool:
        calls.append((message, level))
        return True

    monkeypatch.setattr(mgr, "_send_webhook", fake_webhook)
    result = await mgr.send_routed(
        "system note",
        AlertCategory.SYSTEM_HEALTH,
        AlertPriority.P3_LOW,  # routes to webhook only
        symbol="BTC/USDT",
    )
    assert result == {"webhook": True}  # 321
    assert calls[0][1] == AlertLevel.INFO
