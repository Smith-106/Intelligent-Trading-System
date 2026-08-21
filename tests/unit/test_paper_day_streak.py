"""T023: paper day streak ledger."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load():
    path = REPO / "scripts" / "paper_day_streak.py"
    spec = importlib.util.spec_from_file_location("paper_day_streak", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_summary_credit_ok():
    mod = _load()
    ok, _ = mod.summary_is_credit({"status": "ok", "path": "A", "preflight_rc": 0})
    assert ok is True


def test_summary_reject_preflight():
    mod = _load()
    ok, reason = mod.summary_is_credit(
        {"status": "preflight_failed", "path": "A", "preflight_rc": 1}
    )
    assert ok is False
    assert "preflight" in reason or "status" in reason


def test_summary_reject_hard_deviation():
    mod = _load()
    ok, _ = mod.summary_is_credit(
        {
            "status": "baseline_deviation_alert",
            "path": "A",
            "deviation": {"status": "alert", "health_ok": False},
        }
    )
    assert ok is False


def test_soft_degraded_still_credits():
    mod = _load()
    ok, _ = mod.summary_is_credit(
        {
            "status": "baseline_deviation_degraded",
            "path": "A",
            "preflight_rc": 0,
            "deviation": {"status": "degraded", "health_ok": True},
        }
    )
    assert ok is True


def test_ingest_and_consecutive(tmp_path: Path, monkeypatch):
    mod = _load()
    sessions = tmp_path / "paper_sessions"
    sessions.mkdir()
    monkeypatch.setattr(mod, "SESSIONS_DIR", sessions)
    monkeypatch.setattr(mod, "LEDGER_PATH", sessions / "streak_ledger.json")

    today = datetime.now(UTC).date()
    # credit today and yesterday
    for _i, d in enumerate([today - timedelta(days=1), today]):
        stamp = d.strftime("%Y%m%d") + "T120000Z"
        payload = {
            "kind": "paper_day_session",
            "path": "A",
            "status": "ok",
            "preflight_rc": 0,
            "started_at": datetime(d.year, d.month, d.day, 12, 0, tzinfo=UTC).isoformat(),
            "deviation": {"status": "ok", "health_ok": True},
            "baseline_snapshot": {"decision": "PAPER-GO"},
        }
        (sessions / f"day_session_{stamp}.json").write_text(json.dumps(payload), encoding="utf-8")

    ledger = mod.ingest_files(mod.load_ledger())
    stats = mod.streak_stats(ledger, min_days=2)
    assert stats["n_credited"] == 2
    assert stats["consecutive_ending_recent"] >= 2
    assert stats["target_met_consecutive"] is True


def test_parse_day_from_filename():
    mod = _load()
    d = mod._parse_day("day_session_20260808T141330Z.json")
    assert d == date(2026, 8, 8)
