"""T012: Wave-C style upgrade adjudication (no full replay)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load():
    path = REPO / "scripts" / "run_baseline1_challenger.py"
    spec = importlib.util.spec_from_file_location("run_baseline1_challenger", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_adjudicate_keeps_baseline0_when_challenger_weak():
    mod = _load()
    rows = [
        {
            "label": "classic",
            "wfo_oos_mean_sharpe": 0.5,
            "wfo_oos_sum_pct": 5.0,
            "full_max_dd_pct": 10.0,
        },
        {
            "label": "donchian",
            "wfo_oos_mean_sharpe": -0.2,
            "wfo_oos_sum_pct": -1.0,
            "full_max_dd_pct": 5.0,
        },
    ]
    adj = mod.adjudicate(rows, [])
    assert adj["upgrade_to_baseline1"] is False
    assert adj["keep_baseline0"] is True
    assert adj["verdict"] == "KEEP_BASELINE_0"


def test_adjudicate_upgrade_when_challenger_dominates():
    mod = _load()
    rows = [
        {
            "label": "classic",
            "wfo_oos_mean_sharpe": 0.2,
            "wfo_oos_sum_pct": 2.0,
            "full_max_dd_pct": 12.0,
        },
        {
            "label": "donchian",
            "wfo_oos_mean_sharpe": 0.5,
            "wfo_oos_sum_pct": 8.0,
            "full_max_dd_pct": 10.0,
        },
    ]
    adj = mod.adjudicate(rows, [])
    assert adj["upgrade_to_baseline1"] is True
    assert adj["verdict"] == "UPGRADE_BASELINE_1"
    assert adj["best_challenger"] == "donchian"
