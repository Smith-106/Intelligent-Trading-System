"""Integration tests: paper TradingSession lifecycle + multi-symbol recovery (ENG-UP-01).

Expansion beyond tests/integration/test_session_recovery.py (TASK-003):
- paper mode start sets the session running; stop clears running and
  disconnects the gateway (lifecycle start/stop)
- multi-symbol start(symbols=["BTC/USDT", "ETH/USDT"]) records both symbols
- multi-symbol checkpoint restore recovers cash + positions for >= 2 symbols
  when the FakeGateway book matches the checkpoint (verified recovery)
- one-symbol exchange drift after a multi-symbol restore -> recovery_unverified
  -> new BUY entries blocked (fail-closed), FLAT close still allowed
- drift corrected -> re-verify -> entries allowed again

Deterministic only: FakeGateway double, no real exchange, no live mode,
promotion_eligible untouched.
"""

from __future__ import annotations

import pytest

from quantflow.common.config import AppConfig
from quantflow.common.event_bus import EVENT_RISK
from quantflow.common.models import Direction, Position, Signal
from quantflow.common.validators import POSITION_EPSILON
from quantflow.execution.state_store import SessionSnapshot, StateStore
from quantflow.strategy.engine import TradingSession

SYMBOLS = ["BTC/USDT", "ETH/USDT"]


class FakeGateway:
    """GatewayBase-shaped deterministic double (no network).

    Implements the surface the session/reconciliation/kill-switch paths use:
    connect/disconnect lifecycle, query_positions (exchange book), open-order
    queries, order submission and cancel-all recording.
    """

    def __init__(self, positions: list[Position] | None = None) -> None:
        self._positions = list(positions or [])
        self.connected = False
        self.disconnected = False
        self.sent_orders: list = []
        self.cancelled_all_count = 0

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
        return []

    async def send_order(self, order) -> str:
        self.sent_orders.append(order)
        return f"fake-{len(self.sent_orders)}"

    def update_market_price(self, symbol: str, price: float) -> None:
        # No-op — the fake has no local orderbook; prices come via signals.
        return


def _make_config(tmp_path, *, state_enabled: bool = True) -> AppConfig:
    config = AppConfig()
    config.state.enabled = state_enabled
    config.state.checkpoint_dir = str(tmp_path / "checkpoints")
    return config


def _attach_gateway(session: TradingSession, gateway: FakeGateway) -> None:
    """Inject a fake gateway before start().

    ExecutionEngine.start() returns early when a gateway is already attached
    (connect-only), so the OrderRouter must be rebound to the fake for order
    dispatch — mirroring what start() does for an internally built gateway.
    """
    session._execution._gateway = gateway
    session._execution._router.set_gateway(gateway)


def _matching_positions() -> list[Position]:
    return [
        Position(
            symbol="BTC/USDT",
            quantity=0.5,
            entry_price=50_000.0,
            current_price=51_000.0,
            unrealized_pnl=500.0,
            strategy_id="trend",
        ),
        Position(
            symbol="ETH/USDT",
            quantity=2.0,
            entry_price=3_000.0,
            current_price=3_100.0,
            unrealized_pnl=200.0,
            strategy_id="trend",
        ),
    ]


def _drifted_positions() -> list[Position]:
    """Exchange book where ETH/USDT drifted 25% vs the checkpoint (>> 100 bps)."""
    return [
        Position(
            symbol="BTC/USDT",
            quantity=0.5,
            entry_price=50_000.0,
            current_price=51_000.0,
            unrealized_pnl=500.0,
            strategy_id="trend",
        ),
        Position(
            symbol="ETH/USDT",
            quantity=1.5,  # checkpoint says 2.0 -> 5000 bps drift
            entry_price=3_000.0,
            current_price=3_100.0,
            unrealized_pnl=150.0,
            strategy_id="trend",
        ),
    ]


def _write_multi_symbol_checkpoint(tmp_path, *, cash: float = 95_000.0) -> None:
    store = StateStore(str(tmp_path / "checkpoints"))
    store.save_checkpoint(
        SessionSnapshot(
            saved_at_ms=1_700_000_000_000,
            mode="paper",
            cash=cash,
            positions=[
                {
                    "symbol": "BTC/USDT",
                    "quantity": 0.5,
                    "entry_price": 50_000.0,
                    "current_price": 51_000.0,
                    "unrealized_pnl": 500.0,
                    "strategy_id": "trend",
                },
                {
                    "symbol": "ETH/USDT",
                    "quantity": 2.0,
                    "entry_price": 3_000.0,
                    "current_price": 3_100.0,
                    "unrealized_pnl": 200.0,
                    "strategy_id": "trend",
                },
            ],
            open_orders=[],
            equity=cash + 0.5 * 51_000.0 + 2.0 * 3_100.0,
        )
    )


def _buy_signal(symbol: str = "BTC/USDT") -> Signal:
    return Signal(
        symbol=symbol,
        direction=Direction.LONG,
        strength=0.8,
        price=51_000.0,
        strategy_id="trend",
    )


def _flat_signal(symbol: str = "BTC/USDT") -> Signal:
    return Signal(
        symbol=symbol,
        direction=Direction.FLAT,
        strength=1.0,
        price=51_000.0,
        strategy_id="trend",
    )


class TestPaperLifecycle:
    @pytest.mark.asyncio
    async def test_paper_start_sets_session_running(self, tmp_path) -> None:
        session = TradingSession(_make_config(tmp_path), strategies=[])
        _attach_gateway(session, FakeGateway())  # attach before start
        await session.start(mode="paper")

        assert session._running is True
        assert session.check_health()["running"] is True
        assert session._session_mode == "paper"
        await session.stop()

    @pytest.mark.asyncio
    async def test_paper_stop_clears_running_and_disconnects_gateway(self, tmp_path) -> None:
        session = TradingSession(_make_config(tmp_path), strategies=[])
        gateway = FakeGateway()
        _attach_gateway(session, gateway)
        await session.start(mode="paper")
        assert session._running is True

        await session.stop()

        assert session._running is False
        assert session.check_health()["running"] is False
        assert gateway.disconnected is True


class TestPaperMultiSymbolStart:
    @pytest.mark.asyncio
    async def test_multi_symbol_start_records_both_symbols(self, tmp_path) -> None:
        session = TradingSession(_make_config(tmp_path), strategies=[])
        _attach_gateway(session, FakeGateway())
        await session.start(mode="paper", symbols=SYMBOLS)

        assert set(session._symbols) == {"BTC/USDT", "ETH/USDT"}
        await session.stop()


class TestPaperMultiSymbolRecovery:
    @pytest.mark.asyncio
    async def test_multi_symbol_restore_recovers_cash_and_positions(self, tmp_path) -> None:
        """Checkpoint with 2 positions + matching exchange book -> verified restore."""
        _write_multi_symbol_checkpoint(tmp_path)
        session = TradingSession(_make_config(tmp_path), strategies=[])
        _attach_gateway(session, FakeGateway(_matching_positions()))
        await session.start(mode="paper")

        assert session._recovery_verified is True
        assert session.portfolio.cash == pytest.approx(95_000.0, abs=POSITION_EPSILON)
        btc = session.portfolio.get_position("BTC/USDT")
        assert btc is not None
        assert btc.quantity == pytest.approx(0.5, abs=POSITION_EPSILON)
        eth = session.portfolio.get_position("ETH/USDT")
        assert eth is not None
        assert eth.quantity == pytest.approx(2.0, abs=POSITION_EPSILON)
        assert set(session.portfolio.positions.keys()) == {"BTC/USDT", "ETH/USDT"}
        await session.stop()

    @pytest.mark.asyncio
    async def test_one_symbol_drift_blocks_entries_but_allows_flat(self, tmp_path) -> None:
        """ETH book drifts vs the restored checkpoint -> fail-closed gate.

        BUY is refused with reason recovery_unverified on the drifted book;
        FLAT close still passes the gate (exit-safe), exactly one close order
        is submitted and no second block fires.
        """
        _write_multi_symbol_checkpoint(tmp_path)
        session = TradingSession(_make_config(tmp_path), strategies=[])
        _attach_gateway(session, FakeGateway(_drifted_positions()))
        blocked: list[str] = []
        session.event_bus.subscribe(
            EVENT_RISK,
            lambda e: (
                blocked.append(e.data.get("reason", ""))
                if e.data.get("type") == "signal_blocked"
                else None
            ),
        )
        await session.start(mode="paper")

        assert session._recovery_verified is False
        # New entry refused before the risk check — no order is ever tracked.
        await session._process_signal(_buy_signal("ETH/USDT"))
        assert "recovery_unverified" in blocked
        assert session.execution.order_manager.total_orders == 0

        # FLAT close is exempt: the gate lets it through, exactly one order.
        session.execution.update_market_price("ETH/USDT", 3_100.0)
        await session._process_signal(_flat_signal("ETH/USDT"))
        assert blocked.count("recovery_unverified") == 1  # no second block
        assert session.execution.order_manager.total_orders == 1  # close attempted
        await session.stop()

    @pytest.mark.asyncio
    async def test_recovery_verified_after_book_corrected_allows_entries(self, tmp_path) -> None:
        """Drift on one symbol keeps entries blocked; once the exchange book
        matches the restored book and re-verification passes, entries flow."""
        _write_multi_symbol_checkpoint(tmp_path)
        session = TradingSession(_make_config(tmp_path), strategies=[])
        gateway = FakeGateway(_drifted_positions())
        _attach_gateway(session, gateway)
        blocked: list[str] = []
        session.event_bus.subscribe(
            EVENT_RISK,
            lambda e: (
                blocked.append(e.data.get("reason", ""))
                if e.data.get("type") == "signal_blocked"
                else None
            ),
        )
        await session.start(mode="paper")
        assert session._recovery_verified is False

        # Correct the exchange book for ETH/USDT and re-verify.
        gateway._positions = _matching_positions()
        session._recovery_verified = await session._verify_recovery()
        assert session._recovery_verified is True

        session.execution.update_market_price("BTC/USDT", 51_000.0)
        await session._process_signal(_buy_signal("BTC/USDT"))
        assert "recovery_unverified" not in blocked
        await session.stop()
