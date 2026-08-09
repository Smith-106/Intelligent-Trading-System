"""T013: baseline2 challenger loads and reuses Wave-C adjudicate."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load_b2():
    path = REPO / "scripts" / "run_baseline2_challenger.py"
    spec = importlib.util.spec_from_file_location("run_baseline2_challenger", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_b2_variants_are_complementary_not_nonma():
    mod = _load_b2()
    labels = {v[0] for v in mod.VARIANTS}
    assert "classic" in labels
    assert "mean_reversion" in labels
    assert "volatility_breakout" in labels
    assert "donchian" not in labels


def test_b2_adjudicate_loader_keeps_weak_challenger():
    mod = _load_b2()
    adjudicate = mod._load_adjudicate()
    rows = [
        {
            "label": "classic",
            "wfo_oos_mean_sharpe": 0.1,
            "wfo_oos_sum_pct": 1.0,
            "full_max_dd_pct": 10.0,
        },
        {
            "label": "mean_reversion",
            "wfo_oos_mean_sharpe": -1.0,
            "wfo_oos_sum_pct": -5.0,
            "full_max_dd_pct": 20.0,
        },
    ]
    adj = adjudicate(rows, [])
    assert adj["upgrade_to_baseline1"] is False
    assert adj["keep_baseline0"] is True
