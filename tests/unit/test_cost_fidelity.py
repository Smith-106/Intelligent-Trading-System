"""Unit tests for promotion cost-fidelity gate (P0 T001)."""

from __future__ import annotations

import pytest

from quantflow.strategy.validation.cost_fidelity import (
    CostFidelityError,
    assert_promotion_cost_ready,
    attach_cost_fidelity,
    reject_zero_cost_only_go,
    require_cost_grid,
    require_dual_risk_report,
)


def _grid_ok() -> list[dict]:
    return [
        {"taker_fee": 0.0, "slippage": 0.0, "sharpe": 1.0, "return_pct": 20.0},
        {"taker_fee": 0.001, "slippage": 0.001, "sharpe": 0.55, "return_pct": 10.0},
    ]


def test_require_cost_grid_missing():
    with pytest.raises(CostFidelityError, match="missing"):
        require_cost_grid({"decision": "GO"})


def test_require_cost_grid_needs_zero_and_default():
    with pytest.raises(CostFidelityError, match="zero-cost"):
        require_cost_grid(
            {
                "fee_slip_grid": [
                    {"taker_fee": 0.001, "slippage": 0.001, "sharpe": 0.5},
                ]
            }
        )


def test_reject_zero_cost_only():
    report = {
        "fee_slip_grid": [
            {"taker_fee": 0.0, "slippage": 0.0, "sharpe": 1.2, "return_pct": 40.0},
            {"taker_fee": 0.001, "slippage": 0.001, "sharpe": -0.05, "return_pct": -1.0},
        ]
    }
    with pytest.raises(CostFidelityError, match="zero-cost-only"):
        reject_zero_cost_only_go(report)


def test_assert_promotion_cost_ready_ok():
    assert_promotion_cost_ready({"decision": "GO", "fee_slip_grid": _grid_ok()})


def test_attach_cost_fidelity():
    out = attach_cost_fidelity({"decision": "GO"}, fee_slip_grid=_grid_ok())
    assert "fee_slip_grid" in out
    assert out["checks"]["cost_fidelity"]["passed"] is True


def test_dual_risk_report():
    rows = [
        {"case": "research_bypass", "research_risk_bypass": True, "return_pct": 20.0},
        {"case": "prod_risk_dd10", "research_risk_bypass": False, "return_pct": 8.0},
    ]
    got = require_dual_risk_report({"risk_ablation": rows})
    assert len(got) == 2
