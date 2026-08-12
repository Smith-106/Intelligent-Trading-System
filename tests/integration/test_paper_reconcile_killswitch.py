"""Integration tests: multi-symbol reconcile + paper kill-switch path (ENG-UP-01).

TASK-004 expansion beyond tests/integration/test_reconciliation_wiring.py:
- multi-symbol reconciliation: local books for BTC/USDT AND ETH/USDT drift vs
  the FakeGateway exchange book -> critical reconciliation_drift alert via
  RecordingSink through _periodic_maintenance (2 discrepancies)
- paper session with config.risk.kill_switch_enabled=True and a gateway
  attached at start arms the KillSwitch (session.kill_switch + engine wiring)
- activate_kill_switch(reason) cancels all orders and closes every open
  position through the FakeGateway, reports status=activated / is_active=True
- no kill switch configured -> activate_kill_switch raises (fail-closed)

Deterministic only: FakeGateway + RecordingSink doubles, no live exchange,
promotion_eligible untouched.
"""

from __future__ import annotations

import pytest

from quantflow.common.config import AppConfig
from quantflow.common.models import Position
from quantflow.common.monitoring_sink import NullMonitoringSink
from quantflow.strategy.engine import TradingSession
from quantflow.strategy.templates.funding_rate import FundingRateStrategy

BTC = "BTC/USDT"
ETH = "ETH/USDT"


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
    """GatewayBase-shaped double recording every interaction (no network)."""

    def __init__(self, positions: list[Position] | None = None) -> None:
        self._positions = list(positions or [])
        self.connected = False
        self.disconnected = False
        self.cancelled_all_count = 0
        self.cancelled_all_calls: list[list] = []
        self.sent_orders: list = []

    async def connect(self, gateway_config: dict | None = None) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def query_positions(self) -> list[Position]:
        return list(self._positions)

    async def query_open_orders(self, symbol: str = "") -> list:
        return []

    async def cancel_all_orders(self) -> list:
        self.cancelled_all_count += 1
        self.cancelled_all_calls.append(list(self._positions))
        return []

    async def send_order(self, order) -> str:
        self.sent_orders.append(order)
        return f"fake-{len(self.sent_orders)}"

    def update_market_price(self, symbol: str, price: float) -> None:
        # No-op — the fake has no local orderbook.
        return


def _local_position(symbol: str, quantity: float) -> Position:
    return Position(
        symbol=symbol,
        quantity=quantity,
        entry_price=50_000.0,
        current_price=50_000.0,
        strategy_id="t",
    )


def _make_session(sink: RecordingSink | None = None, *, recon_enabled: bool) -> TradingSession:
    config = AppConfig()
    config.reconciliation.enabled = recon_enabled
    config.reconciliation.interval_minutes = 1
    session = TradingSession(
        config,
        [FundingRateStrategy()],
        monitoring_sink=sink or RecordingSink(),
    )
    return session


class TestMultiSymbolReconcileDrift:
    @pytest.mark.asyncio
    async def test_multi_symbol_drift_alert_via_periodic_maintenance(self) -> None:
        """Both local books drift vs exchange -> critical alert, 2 discrepancies."""
        sink = RecordingSink()
        session = _make_session(sink, recon_enabled=True)
        session._portfolio.positions[BTC] = _local_position(BTC, 1.0)
        session._portfolio.positions[ETH] = _local_position(ETH, 2.0)
        session._execution._gateway = FakeGateway(
            [_local_position(BTC, 1.2), _local_position(ETH, 1.6)]
        )
        session._build_reconciliation_engine()
        assert session._reconciliation_engine is not None

        session._last_reconciliation_at = 0.0  # force the interval to be due
        await session._periodic_maintenance()

        assert sink.alerts, "expected a drift alert through the sink"
        alert = sink.alerts[-1]
        assert alert["level"] == "critical"
        assert alert["extra"].get("category") == "reconciliation_drift"
        assert alert["extra"].get("total_discrepancies") == 2
        assert "2 discrepancies" in alert["message"]

    @pytest.mark.asyncio
    async def test_multi_symbol_no_alert_when_books_match(self) -> None:
        """Matching multi-symbol books -> zero discrepancies -> no alert."""
        sink = RecordingSink()
        session = _make_session(sink, recon_enabled=True)
        session._portfolio.positions[BTC] = _local_position(BTC, 1.0)
        session._portfolio.positions[ETH] = _local_position(ETH, 2.0)
        session._execution._gateway = FakeGateway(
            [_local_position(BTC, 1.0), _local_position(ETH, 2.0)]
        )
        session._build_reconciliation_engine()

        session._last_reconciliation_at = 0.0
        await session._periodic_maintenance()

        assert sink.alerts == []


class TestPaperKillSwitchArm:
    @pytest.mark.asyncio
    async def test_paper_start_arms_kill_switch_when_enabled_and_gateway_present(
        self,
        tmp_path,
    ) -> None:
        config = AppConfig()
        config.risk.kill_switch_enabled = True  # explicit (plan: config-gated)
        session = TradingSession(config, strategies=[])
        gateway = FakeGateway()
        session._execution._gateway = gateway
        session._execution._router.set_gateway(gateway)

        await session.start(mode="paper")

        assert session.kill_switch is not None
        assert session.kill_switch.is_active is False
        # Wired into the engine so submit() blocks new orders when active.
        assert session._execution._kill_switch is session.kill_switch
        await session.stop()

    @pytest.mark.asyncio
    async def test_paper_start_does_not_arm_when_disabled(self, tmp_path) -> None:
        config = AppConfig()
        config.risk.kill_switch_enabled = False
        session = TradingSession(config, strategies=[])
        gateway = FakeGateway()
        session._execution._gateway = gateway
        session._execution._router.set_gateway(gateway)

        await session.start(mode="paper")

        assert session.kill_switch is None
        await session.stop()


class TestPaperKillSwitchActivate:
    @pytest.mark.asyncio
    async def test_activate_cancels_all_and_closes_positions(self, tmp_path) -> None:
        config = AppConfig()
        config.risk.kill_switch_enabled = True
        session = TradingSession(config, strategies=[])
        gateway = FakeGateway(
            [
                _local_position(BTC, 0.5),
                _local_position(ETH, 2.0),
            ]
        )
        session._execution._gateway = gateway
        session._execution._router.set_gateway(gateway)
        await session.start(mode="paper")
        assert session.kill_switch is not None

        result = await session.activate_kill_switch("integration_test")

        assert result["status"] == "activated"
        assert session.kill_switch.is_active is True
        assert session.kill_switch.reason == "integration_test"
        assert gateway.cancelled_all_count == 1
        assert len(result["cancelled_orders"]) == 0  # fake cancels nothing open
        # One market close order per open position, reduceOnly params preserved.
        assert len(gateway.sent_orders) == 2
        assert {o.symbol for o in gateway.sent_orders} == {BTC, ETH}
        assert all(o.params.get("reduceOnly") is True for o in gateway.sent_orders)
        assert {c["symbol"] for c in result["closed_positions"]} == {BTC, ETH}
        await session.stop()

    @pytest.mark.asyncio
    async def test_activate_raises_when_no_kill_switch_armed(self, tmp_path) -> None:
        config = AppConfig()
        config.risk.kill_switch_enabled = False
        session = TradingSession(config, strategies=[])
        gateway = FakeGateway()
        session._execution._gateway = gateway
        session._execution._router.set_gateway(gateway)
        await session.start(mode="paper")

        with pytest.raises(RuntimeError, match="No active session kill switch"):
            await session.activate_kill_switch("integration_test")
        await session.stop()
