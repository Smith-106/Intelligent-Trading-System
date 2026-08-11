"""Wave B3/B4: paper_day_session --orderbook-fill wiring (default OFF)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _load_pds_module():  # type: ignore[no-untyped-def]
    path = REPO / "scripts" / "paper_day_session.py"
    spec = importlib.util.spec_from_file_location("paper_day_session", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_orderbook_overlay_yaml_enables_fill_and_poll() -> None:
    raw = yaml.safe_load(
        (REPO / "quantflow" / "config" / "paper_day_orderbook_overlay.yaml").read_text(
            encoding="utf-8"
        )
    )
    ex = raw["execution"]
    assert ex["orderbook_fill_enabled"] is True
    assert ex["orderbook_fill"]["enabled"] is True
    assert ex["bbo_poll_enabled"] is True
    assert float(ex["bbo_poll_interval_s"]) > 0
    assert ex.get("mode") == "paper"


def test_baseline_overlay_does_not_enable_orderbook_fill() -> None:
    raw = yaml.safe_load(
        (REPO / "quantflow" / "config" / "paper_baseline0_overlay.yaml").read_text(encoding="utf-8")
    )
    ex = raw.get("execution") or {}
    assert ex.get("orderbook_fill_enabled") in (None, False)
    assert (ex.get("orderbook_fill") or {}).get("enabled") in (None, False)
    assert ex.get("bbo_poll_enabled") in (None, False)


def test_orderbook_fill_flag_switches_default_config(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mod = _load_pds_module()
    # Avoid real preflight / writes
    monkeypatch.setattr(mod, "_preflight", lambda: 0)
    written: list[dict] = []

    def _fake_write(payload: dict) -> Path:  # type: ignore[type-arg]
        written.append(payload)
        return REPO / "data" / "paper_sessions" / "_test_summary.json"

    monkeypatch.setattr(mod, "_write_summary", _fake_write)
    monkeypatch.setattr(mod, "_maybe_alert", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_attach_baseline_deviation", lambda s, **k: s)

    # Invoke via argv
    monkeypatch.setattr(
        sys,
        "argv",
        ["paper_day_session.py", "--skip-preflight", "--skip-deviation", "--orderbook-fill"],
    )
    code = mod.main()
    assert code == 0
    assert written, "summary should be written"
    contract = written[0]["contract"]
    assert contract["orderbook_fill"] is True
    assert contract["bbo_poll_requested"] is True
    assert "orderbook" in contract["config"]


def test_default_argv_keeps_baseline_overlay(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mod = _load_pds_module()
    monkeypatch.setattr(mod, "_preflight", lambda: 0)
    written: list[dict] = []
    monkeypatch.setattr(
        mod,
        "_write_summary",
        lambda payload: written.append(payload) or (REPO / "data" / "paper_sessions" / "x.json"),
    )
    monkeypatch.setattr(mod, "_maybe_alert", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_attach_baseline_deviation", lambda s, **k: s)
    monkeypatch.setattr(
        sys,
        "argv",
        ["paper_day_session.py", "--skip-preflight", "--skip-deviation"],
    )
    assert mod.main() == 0
    assert written[0]["contract"]["orderbook_fill"] is False
    assert written[0]["contract"]["config"].endswith("paper_baseline0_overlay.yaml")


def test_help_lists_orderbook_fill() -> None:
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "paper_day_session.py"), "--help"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0
    assert "--orderbook-fill" in (proc.stdout or "")
