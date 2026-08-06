"""Session-level wiring tests for the T-s1-04 exchange health monitor.

ISS-20260803-003: the ExchangeHealthMonitor + exposure cap components existed
and were unit-tested, but TradingSession never constructed the monitor nor
injected it into RiskEngine / ExecutionEngine → OKXGateway — the circuit
breaker and exposure cap were dead in production. These tests pin the
production composition:

- exchange_health.enabled=true -> monitor shared by RiskEngine + ExecutionEngine
- breaker trip -> RiskEngine.check rejects new entries (fail-closed)
- exchange_exposure_limit_pct -> propagated to RiskEngine
- enabled=false -> all seams stay None (byte-for-byte zero behavior change)
"""

from __future__ import annotations

from quantflow.common.config import AppConfig
from quantflow.common.models import Direction, Portfolio, Signal
from quantflow.strategy.engine import TradingSession
from quantflow.strategy.templates.funding_rate import FundingRateStrategy


def _make_session(*, health_enabled: bool, exposure_limit: float | None = 0.8) -> TradingSession:
    config = AppConfig()
    config.risk.exchange_health.enabled = health_enabled
    config.risk.exchange_exposure_limit_pct = exposure_limit
    return TradingSession(config, [FundingRateStrategy()])


class TestExchangeHealthWiring:
    def test_enabled_injects_shared_monitor_into_risk_and_execution(self) -> None:
        session = _make_session(health_enabled=True)
        monitor = session._exchange_health
        assert monitor is not None
        # One shared instance feeds both the checks and the outcome recording.
        assert session._risk_engine._exchange_health is monitor
        assert session._execution._health_monitor is monitor
        # Breaker starts closed.
        assert monitor.circuit_open() is False

    def test_enabled_propagates_exposure_limit(self) -> None:
        session = _make_session(health_enabled=True, exposure_limit=0.8)
        assert session._risk_engine._exchange_exposure_limit_pct == 0.8

    def test_disabled_keeps_health_seams_none_exposure_from_config(self) -> None:
        """health disabled -> monitor seams None; exposure cap is independent."""
        session = _make_session(health_enabled=False, exposure_limit=0.8)
        assert session._exchange_health is None
        assert session._risk_engine._exchange_health is None
        assert session._execution._health_monitor is None
        # Exposure cap is configured independently of the breaker (default 0.8).
        assert session._risk_engine._exchange_exposure_limit_pct == 0.8

    def test_exposure_none_when_not_configured(self) -> None:
        session = _make_session(health_enabled=False, exposure_limit=None)
        assert session._risk_engine._exchange_exposure_limit_pct is None

    def test_tripped_breaker_rejects_new_entries(self) -> None:
        """Fail-closed: a tripped breaker blocks entries via RiskEngine.check."""
        session = _make_session(health_enabled=True)
        monitor = session._exchange_health
        assert monitor is not None
        # 3 consecutive OKX 50011 rate-limit errors trip the breaker.
        for _ in range(3):
            monitor.record_rate_limited()
        assert monitor.circuit_open() is True

        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50_000)
        pf = Portfolio(cash=100_000)
        result = session._risk_engine.check(sig, pf)
        assert not result.passed
        assert result.reason == "exchange_circuit_open"

    def test_exposure_cap_blocks_entry_when_breached(self) -> None:
        """Exposure > cap blocks LONG entries only (exits stay passable)."""
        session = _make_session(health_enabled=False, exposure_limit=0.1)
        pf = Portfolio(cash=100_000)
        from quantflow.common.models import Position

        # 0.25 BTC x 50k = 12.5% notional: > 10% exposure cap, but < 20%
        # position_limit so the exposure check is the binding one.
        pf.positions["BTC/USDT"] = Position(
            symbol="BTC/USDT",
            quantity=0.25,
            entry_price=50_000.0,
            current_price=50_000.0,
            strategy_id="t",
        )
        long_sig = Signal("ETH/USDT", Direction.LONG, 0.8, 10_000)
        result = session._risk_engine.check(long_sig, pf)
        assert not result.passed
        assert result.reason == "exchange_exposure_exceeded"
        flat_sig = Signal("BTC/USDT", Direction.FLAT, 0.5, 50_000)
        assert session._risk_engine.check(flat_sig, pf).passed
