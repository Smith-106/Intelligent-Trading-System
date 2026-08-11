"""Tests for dual-path research report envelope."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quantflow.strategy.research.dual_path_report import (
    CONTRACT_ID,
    assert_no_combined_score,
    build_dual_path_report,
    dual_path_report_to_promotion_view,
    from_overlay_eval,
    from_tpsl_eval,
    to_json,
    to_markdown,
    write_report,
)
from quantflow.strategy.validation.promotion_path import (
    PromotionPathError,
    assert_promotion_path_ready,
    extract_data_fingerprint,
    extract_execution_path,
)


def test_build_report_no_combined_score() -> None:
    r = build_dual_path_report(
        path_a={"metrics": {"excess_return_pct": 47.0, "max_dd_pct": 69.0}},
        path_b={"metrics": {"excess_return_pct": 4.0, "max_dd_pct": 21.0, "winrate": 0.39}},
    )
    d = r.to_dict()
    assert d["contract"] == CONTRACT_ID
    assert "path_a" in d["paths"] and "path_b" in d["paths"]
    assert d["paths"]["path_a"]["promotion_eligible"] is False
    assert d["paths"]["path_b"]["promotion_eligible"] is False
    assert "combined_score" not in d
    assert_no_combined_score(d)


def test_forbidden_key_raises() -> None:
    with pytest.raises(ValueError, match="combined_score"):
        assert_no_combined_score({"paths": {"combined_score": 1.0}})
    with pytest.raises(ValueError, match="best_score"):
        build_dual_path_report(
            path_a={"best_score": 9},
            path_b={"metrics": {}},
        )


def test_from_overlay_and_tpsl_adapters() -> None:
    overlay = {
        "primary_overlay_reduce_off": {
            "meta": {"overlay_weight": 0.3},
            "return_pct": 165.0,
            "excess_return_pct": 47.09,
            "max_dd_pct": 69.47,
            "gate": "PASS",
        }
    }
    tpsl = {
        "tpsl_default": {
            "return_pct": 122.5,
            "excess_return_pct": 3.98,
            "max_dd_pct": 21.13,
            "gate": "PASS",
            "trade_stats": {"winrate": 0.391, "payoff_ratio": 2.5, "n_trades": 69},
            "config": {"stop_loss_pct": 0.04},
        }
    }
    a = from_overlay_eval(overlay)
    b = from_tpsl_eval(tpsl)
    r = build_dual_path_report(path_a=a, path_b=b)
    assert r.paths["path_a"]["metrics"]["excess_return_pct"] == pytest.approx(47.09)
    assert r.paths["path_b"]["metrics"]["payoff_ratio"] == pytest.approx(2.5)
    # adapters must not copy score keys into metrics
    assert "score" not in (r.paths["path_b"].get("metrics") or {})


def test_markdown_has_two_sections() -> None:
    r = build_dual_path_report(
        path_a={"metrics": {"excess_return_pct": 1}},
        path_b={"metrics": {"excess_return_pct": 2}},
    )
    md = to_markdown(r)
    assert "Path A" in md and "Path B" in md
    assert "combined_score" not in md.lower() or "No `combined_score`" in md
    assert "综合得分" not in md


def test_write_report(tmp_path: Path) -> None:
    r = build_dual_path_report(
        path_a={"metrics": {"return_pct": 1.0}},
        path_b={"metrics": {"return_pct": 2.0}},
    )
    jp = tmp_path / "out.json"
    mp = tmp_path / "out.md"
    write_report(r, jp, out_md=mp)
    loaded = json.loads(jp.read_text(encoding="utf-8"))
    assert loaded["paths"]["path_a"]["metrics"]["return_pct"] == 1.0
    assert mp.is_file()
    assert "DUAL-PATH-RESEARCH-OS" in to_json(r)
    assert "Path A" in mp.read_text(encoding="utf-8")


def test_imp01_attaches_fingerprint_and_honest_path() -> None:
    r = build_dual_path_report(
        path_a={"metrics": {"excess_return_pct": 1.0}},
        path_b={"metrics": {"excess_return_pct": 2.0}},
        data_fingerprint={"aggregate": "deadbeef", "bars": 10},
    )
    d = r.to_dict()
    assert d["run_meta"]["execution_path"] == "vectorized"
    assert d["run_meta"]["data_fingerprint"]["aggregate"] == "deadbeef"
    promo = d["attachments"]["promotion_path"]
    assert promo["promotion_eligible"] is False
    assert promo["register_ready"] is False
    assert promo["data_fingerprint"]["aggregate"] == "deadbeef"

    view = dual_path_report_to_promotion_view(r)
    assert extract_execution_path(view) == "vectorized"
    assert extract_data_fingerprint(view) is not None
    # Research vectorized path must NOT pass register gate
    with pytest.raises(PromotionPathError):
        assert_promotion_path_ready(view)

    # Forced paper view only for attach helper tests — still needs fingerprint
    paper_view = dual_path_report_to_promotion_view(r, force_paper_path=True)
    assert extract_execution_path(paper_view) == "paper_replay"
    ok = assert_promotion_path_ready(paper_view)
    assert ok["passed"] is True
