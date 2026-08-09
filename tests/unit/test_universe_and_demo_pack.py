"""P2 T008/T009: universe SLA helpers + public demo pack."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    path = REPO / rel
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


universe = _load("universe_expand_pipeline", "scripts/universe_expand_pipeline.py")
demo = _load("demo_public_pack", "scripts/demo_public_pack.py")


def test_history_quality_score_empty():
    assert universe.history_quality_score(pd.DataFrame(), now_ms=0) == 0.0


def test_history_quality_score_fresh():
    now = 1_700_000_000_000
    stamps = [now - (23 - i) * 3_600_000 for i in range(24)]
    df = pd.DataFrame(
        {
            "timestamp": stamps,
            "close": [100.0 + i * 0.1 for i in range(24)],
        }
    )
    score = universe.history_quality_score(df, now_ms=now)
    assert score >= 0.7


def test_evaluate_symbol_sla_unknown_fails():
    row = universe.evaluate_symbol_sla("ZZZNOPE/USDT")
    assert row["sla_pass"] is False
    assert row["bars"] == 0


def test_demo_public_pack_write_and_check():
    written = demo.write_pack()
    assert written
    assert demo.check_pack() == 0
    gate = json.loads((REPO / "docs/demo/sample_gate.json").read_text(encoding="utf-8"))
    assert "fee_slip_grid" in gate
    assert gate["_meta"]["note"].startswith("SYNTHETIC")
