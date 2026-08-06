"""Integration tests: periodic reconciliation wired into TradingSession.

ISS-20260803-002: the ReconciliationEngine + periodic maintenance existed,
but no test proved the production path — session-level periodic run catching
an artificial drift and emitting a critical alert through the MonitoringSink.
These tests pin the full chain:

    TradingSession._periodic_maintenance
      -> ReconciliationEngine.run_daily_reconciliation
        -> _emit_drift_alert -> MonitoringSink.send_alert(critical)

Acceptance (issue): live periodic execution + artificial drift captured by
the alert channel.
"""

from __future__ import annotations

import pytest

from quantflow.common.config import AppConfig
from quantflow.common.models import Position
from quantflow.common.monitoring_sink import NullMonitoringSink
from quantflow.strategy.engine import TradingSession
from quantflow.strategy.templates.funding_rate import FundingRateStrategy

SYMBOL = "BTC/USDT"


class RecordingSink(NullMonitoringSink):
    """NullMonitoringSink that records send_alert calls."""

    def __init__(self) -> None:
        super().__init__()
        self.alerts: list[dict] = []

    async def send_alert(
        self,
        message: str,
        level: str = "warning",
        extra: dict | None = None,
    ) -> dict:
        self.alerts.append({"message": message, "level": level, "extra": extra or {}})
        return {}


class FakeGateway:
    """GatewayBase-shaped double: exchange book returned by query_positions."""

    def __init__(self, positions: list[Position]) -> None:
        self._positions = positions

    async def query_positions(self) -> list[Position]:
        return self._positions

    async def query_open_orders(self, symbol: str) -> list:
        return []


def _make_session(sink: RecordingSink, *, recon_enabled: bool) -> TradingSession:
    config = AppConfig()
    config.reconciliation.enabled = recon_enabled
    config.reconciliation.interval_minutes = 1
    session = TradingSession(config, [FundingRateStrategy()], monitoring_sink=sink)
    return session


def _local_position(quantity: float) -> Position:
    return Position(
        symbol=SYMBOL,
        quantity=quantity,
        entry_price=50_000.0,
        current_price=50_000.0,
        strategy_id="t",
    )


class TestPeriodicReconciliationWiring:
    @pytest.mark.asyncio
    async def test_drift_alert_captured_through_periodic_maintenance(self) -> None:
        """Artificial drift -> periodic run -> critical alert via sink."""
        sink = RecordingSink()
        session = _make_session(sink, recon_enabled=True)
        # Local book: 1.0 BTC. Exchange book: 1.2 BTC (20% drift >> 1% bps).
        session._portfolio.positions[SYMBOL] = _local_position(1.0)
        session._execution._gateway = FakeGateway([_local_position(1.2)])
        session._build_reconciliation_engine()
        assert session._reconciliation_engine is not None

        session._last_reconciliation_at = 0.0  # force the interval to be due
        await session._periodic_maintenance()

        assert sink.alerts, "expected a drift alert through the sink"
        alert = sink.alerts[-1]
        assert alert["level"] == "critical"
        assert alert["extra"].get("category") == "reconciliation_drift"
        assert "1 discrepancies" in alert["message"]

    @pytest.mark.asyncio
    async def test_periodic_run_skipped_when_disabled(self) -> None:
        """reconciliation.enabled=false -> no engine, no alert."""
        sink = RecordingSink()
        session = _make_session(sink, recon_enabled=False)
        session._portfolio.positions[SYMBOL] = _local_position(1.0)
        session._execution._gateway = FakeGateway([_local_position(1.2)])

        session._last_reconciliation_at = 0.0
        await session._periodic_maintenance()

        assert session._reconciliation_engine is None
        assert sink.alerts == []

    @pytest.mark.asyncio
    async def test_no_alert_when_books_match(self) -> None:
        """Matching books -> zero discrepancies -> no alert."""
        sink = RecordingSink()
        session = _make_session(sink, recon_enabled=True)
        session._portfolio.positions[SYMBOL] = _local_position(1.0)
        session._execution._gateway = FakeGateway([_local_position(1.0)])
        session._build_reconciliation_engine()

        session._last_reconciliation_at = 0.0
        await session._periodic_maintenance()

        assert sink.alerts == []
