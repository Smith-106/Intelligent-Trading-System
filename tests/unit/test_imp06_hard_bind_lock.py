"""IMP-06: IAF / dual-path suite never hard-binds entry into live path."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from quantflow.strategy.research.dual_path_report import (
    RESEARCH_EXECUTION_PATH,
    build_dual_path_report,
    dual_path_report_to_promotion_view,
)
from quantflow.strategy.research.iaf_prune import IAF_FACTOR_NAMES
from quantflow.strategy.research.iaf_prune_cpcv import run_iaf_prune_cpcv
from quantflow.strategy.research.path_b_oos import run_path_b_multi_window_oos

ROOT = Path(__file__).resolve().parents[2]

# Must never assign True to hard_bind_entry in research OS surfaces
_HARD_BIND_TRUE = re.compile(
    r"""hard_bind_entry\s*[=:]\s*True|["']hard_bind_entry["']\s*:\s*True"""
)

MODULES = [
    ROOT / "quantflow" / "strategy" / "research" / "iaf_prune_cpcv.py",
    ROOT / "quantflow" / "strategy" / "research" / "path_b_oos.py",
    ROOT / "quantflow" / "strategy" / "research" / "dual_path_report.py",
    ROOT / "quantflow" / "strategy" / "research" / "multi_symbol_dual_path.py",
    ROOT / "scripts" / "run_dual_path_research_os.py",
    ROOT / "scripts" / "run_path_b_oos.py",
]


def test_source_never_sets_hard_bind_entry_true() -> None:
    for path in MODULES:
        assert path.is_file(), f"missing {path}"
        text = path.read_text(encoding="utf-8")
        m = _HARD_BIND_TRUE.search(text)
        assert m is None, f"{path.name} sets hard_bind_entry True: {m.group(0)!r}"


def test_iaf_prune_cpcv_hard_bind_false() -> None:
    n = 400
    rng = np.random.default_rng(7)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    df = pd.DataFrame(
        {
            "close": close,
            "high": close * 1.001,
            "low": close * 0.999,
            "open": close,
            "volume": rng.uniform(1, 10, n),
        }
    )
    fake = pd.DataFrame({name: rng.normal(size=n) for name in IAF_FACTOR_NAMES})
    with patch(
        "quantflow.strategy.research.iaf_prune_cpcv._compute_iaf_frame",
        return_value=fake,
    ):
        with patch(
            "quantflow.strategy.research.iaf_prune_cpcv.cpcv_backtest",
            return_value={"pbo": 0.3, "passed": False, "n_paths": 8},
        ):
            rep = run_iaf_prune_cpcv(df, cpcv_groups=4, cpcv_test_groups=1)
    assert rep["hard_bind_entry"] is False
    assert rep["promotion_eligible"] is False


def test_path_b_oos_hard_bind_false_on_synth() -> None:
    n = 900
    rng = np.random.default_rng(9)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.008, n)))
    df = pd.DataFrame(
        {
            "close": close,
            "high": close * 1.002,
            "low": close * 0.998,
            "open": close,
            "volume": rng.uniform(1, 5, n),
            "timestamp": np.arange(n) * 3_600_000,
        }
    )
    # small window count for speed
    rep = run_path_b_multi_window_oos(
        df,
        n_windows=2,
        oos_ratio=0.25,
        mode="rolling",
        fixed_params=True,
    )
    assert rep.get("hard_bind_entry") is False
    assert rep.get("promotion_eligible") is False
    assert str(rep.get("execution_path", RESEARCH_EXECUTION_PATH)) == RESEARCH_EXECUTION_PATH


def test_dual_path_promotion_view_not_register_ready() -> None:
    report = build_dual_path_report(
        path_a={"metrics": {"excess_return_pct": 10.0, "gate_vs_btc": "PASS"}},
        path_b={
            "metrics": {"excess_return_pct": 2.0, "gate_vs_btc": "PASS"},
            "promotion_eligible": False,
            "hard_bind_entry": False,
        },
        execution_path=RESEARCH_EXECUTION_PATH,
    )
    d = report.to_dict()
    assert d.get("promotion_eligible") is False or (
        (d.get("attachments") or {}).get("promotion_path") or {}
    ).get("promotion_eligible") in (False, None)
    view = dual_path_report_to_promotion_view(report)
    # vectorized research must not look register-ready for live
    if isinstance(view, dict):
        assert view.get("register_ready") in (False, None)
        assert view.get("promotion_eligible") in (False, None)
        assert "combined_score" not in view
