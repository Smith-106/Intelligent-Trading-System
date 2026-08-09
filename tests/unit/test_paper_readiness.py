"""T016: paper minimum days / fills gate."""

from __future__ import annotations

import pytest

from quantflow.strategy.model_registry import ModelRegistry, ModelRegistryError, STATUS_PAPER
from quantflow.strategy.validation.cost_fidelity import build_funding_tca
from quantflow.strategy.validation.paper_readiness import (
    PaperReadinessConfig,
    PaperReadinessError,
    assert_paper_readiness,
    check_paper_readiness,
)


def _go_report() -> dict:
    return {
        "decision": "GO",
        "fee_slip_grid": [
            {"taker_fee": 0.0, "slippage": 0.0, "sharpe": 1.0, "return_pct": 20.0},
            {"taker_fee": 0.001, "slippage": 0.001, "sharpe": 0.55, "return_pct": 10.0},
        ],
        "funding_tca": build_funding_tca(mode="assumption"),
    }


def test_check_passes_with_enough_sample():
    r = check_paper_readiness({"paper_days": 10, "fills": 50})
    assert r["passed"] is True


def test_check_fails_short_days():
    r = check_paper_readiness({"paper_days": 2, "fills": 100})
    assert r["passed"] is False
    assert any("paper_days" in x for x in r["reasons"])


def test_check_fails_short_fills():
    r = check_paper_readiness({"paper_days": 30, "fills": 3})
    assert r["passed"] is False
    assert any("fills" in x for x in r["reasons"])


def test_assert_raises():
    with pytest.raises(PaperReadinessError, match="fills"):
        assert_paper_readiness({"paper_days": 30, "fills": 1})


def test_disabled_skips():
    r = check_paper_readiness(
        None, config=PaperReadinessConfig(enabled=False)
    )
    assert r["passed"] is True
    assert r.get("skipped") is True


def test_promote_rejects_without_evidence(tmp_path):
    reg = ModelRegistry(tmp_path)
    reg.register("m1", "RF", "h", _go_report())
    with pytest.raises(ModelRegistryError, match="paper readiness"):
        reg.promote_to_live("m1")
    entry = reg.get("m1")
    assert entry is not None
    assert entry["status"] == "rejected"
    assert "paper readiness" in entry["reason"]


def test_promote_accepts_with_evidence(tmp_path):
    reg = ModelRegistry(tmp_path)
    reg.register("m2", "RF", "h", _go_report())
    reg.attach_paper_evidence(
        "m2",
        {
            "paper_days": 14,
            "fills": 40,
            "started_at": "2026-07-01T00:00:00+00:00",
            "ended_at": "2026-07-15T00:00:00+00:00",
        },
    )
    entry = reg.promote_to_live("m2")
    assert entry["status"] == "live"
    assert entry["paper_readiness"]["passed"] is True


def test_promote_inline_evidence(tmp_path):
    reg = ModelRegistry(tmp_path)
    reg.register("m3", "RF", "h", _go_report())
    entry = reg.promote_to_live(
        "m3",
        paper_evidence={"paper_days": 7, "fills": 20},
    )
    assert entry["status"] == "live"
