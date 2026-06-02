"""Tests for lightweight common helpers and edge branches."""

from __future__ import annotations

from quantflow.common.exceptions import RiskBreachError
from quantflow.common.models import Direction, Position


def test_risk_breach_error_exposes_reason_and_severity() -> None:
    error = RiskBreachError("max_drawdown", severity="critical")

    assert error.reason == "max_drawdown"
    assert error.severity == "critical"
    assert "Risk breach: max_drawdown" in str(error)


def test_position_side_returns_flat_for_zero_quantity() -> None:
    position = Position(symbol="BTC/USDT", quantity=0.0, entry_price=50000.0, current_price=50000.0)

    assert position.side is Direction.FLAT
    assert position.market_value == 0.0
