"""Additional branch coverage tests for RiskEngine."""

from __future__ import annotations

from quantflow.common.config import RiskConfig
from quantflow.common.models import Direction, Portfolio, Position, Signal
from quantflow.signal.risk_engine import RiskEngine


def _signal(symbol: str = "BTC/USDT") -> Signal:
    return Signal(symbol=symbol, direction=Direction.LONG, strength=0.8, price=100.0, strategy_id="test")


class TestRiskEngineExtra:
    def test_add_return_trims_history_to_last_500(self) -> None:
        engine = RiskEngine(RiskConfig())

        for i in range(510):
            engine.add_return(float(i))

        assert len(engine._returns_history) == 500
        assert engine._returns_history[0] == 10.0
        assert engine._returns_history[-1] == 509.0

    def test_position_limit_handles_zero_total_value_and_zero_current_price(self) -> None:
        engine = RiskEngine(RiskConfig(position_limit_pct=0.1))
        portfolio = Portfolio(
            cash=0.0,
            positions={"BTC/USDT": Position("BTC/USDT", quantity=1.0, entry_price=100.0, current_price=0.0)},
        )

        result = engine.check(_signal(), portfolio)

        assert result.passed is True

    def test_var_breach_blocks_signal_and_calculates_var_metrics(self) -> None:
        engine = RiskEngine(RiskConfig())
        portfolio = Portfolio(cash=100000.0)
        for _ in range(35):
            engine.add_return(-0.10)
        for _ in range(5):
            engine.add_return(0.01)

        result = engine.check(_signal(), portfolio)

        assert result.passed is False
        assert result.reason == "var_breach"
        assert result.details["var_95"] <= -0.10
        assert result.details["cvar_95"] <= -0.10
        assert engine.calculate_var() <= -0.10
        assert engine.calculate_cvar() <= -0.10

    def test_var_and_cvar_return_zero_without_enough_history(self) -> None:
        engine = RiskEngine(RiskConfig())

        for _ in range(10):
            engine.add_return(-0.01)

        assert engine.calculate_var() == 0.0
        assert engine.calculate_cvar() == 0.0

    def test_var_check_passes_when_tail_risk_is_within_limit(self) -> None:
        engine = RiskEngine(RiskConfig())
        portfolio = Portfolio(cash=100000.0)
        for _ in range(40):
            engine.add_return(-0.01)

        result = engine.check(_signal("ETH/USDT"), portfolio)

        assert result.passed is True

    def test_daily_loss_limit_failure_returns_reason_and_details(self) -> None:
        engine = RiskEngine(RiskConfig(daily_loss_limit=-0.03, position_limit_pct=1.0))
        portfolio = Portfolio(
            cash=47000.0,
            positions={
                "BTC/USDT": Position(
                    "BTC/USDT",
                    quantity=1.0,
                    entry_price=50000.0,
                    current_price=48000.0,
                    unrealized_pnl=-3000.0,
                )
            },
        )

        result = engine.check(_signal(), portfolio)

        assert result.passed is False
        assert result.reason == "daily_loss_limit"
        assert result.details["limit"] == -0.03
