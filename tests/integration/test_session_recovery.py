"""Integration tests for TradingSession checkpoint recovery (T-s1-03).

Scenarios (plan key_scenarios):
- kill -9 equivalent: session restart restores cash/positions from checkpoint
- restored state drifted vs exchange -> recovery_unverified, BUY blocked,
  FLAT (reduce-only close) still allowed (fail-closed but exit-safe)
- verified recovery -> entries allowed again
- state.enabled=false (default) -> zero behavior change
- corrupt checkpoint -> fail-closed
"""

from __future__ import annotations

import pytest

from quantflow.common.config import AppConfig
from quantflow.common.event_bus import EVENT_RISK
from quantflow.common.models import Direction, Position, Signal
from quantflow.common.validators import POSITION_EPSILON
from quantflow.execution.state_store import CHECKPOINT_FILENAME, SessionSnapshot, StateStore
from quantflow.strategy.engine import TradingSession


def _make_config(tmp_path, *, state_enabled: bool = True) -> AppConfig:
    config = AppConfig()
    config.state.enabled = state_enabled
    config.state.checkpoint_dir = str(tmp_path / "checkpoints")
    return config


def _write_checkpoint(tmp_path, *, cash: float = 95_000.0) -> None:
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
                }
            ],
            open_orders=[],
            equity=cash + 0.5 * 51_000.0,
        )
    )


def _buy_signal() -> Signal:
    return Signal(
        symbol="BTC/USDT",
        direction=Direction.LONG,
        strength=0.8,
        price=51_000.0,
        strategy_id="trend",
    )


def _flat_signal() -> Signal:
    return Signal(
        symbol="BTC/USDT",
        direction=Direction.FLAT,
        strength=1.0,
        price=51_000.0,
        strategy_id="trend",
    )


class TestCheckpointRestore:
    @pytest.mark.asyncio
    async def test_restore_matches_checkpoint(self, tmp_path):
        """kill -9 equivalent: restart restores cash/positions exactly."""
        _write_checkpoint(tmp_path)
        session = TradingSession(_make_config(tmp_path), strategies=[])
        await session.start(mode="paper")

        assert session.portfolio.cash == pytest.approx(95_000.0, abs=POSITION_EPSILON)
        pos = session.portfolio.get_position("BTC/USDT")
        assert pos is not None
        assert pos.quantity == pytest.approx(0.5, abs=POSITION_EPSILON)
        assert pos.entry_price == pytest.approx(50_000.0)
        # CORR-M2 reset ran BEFORE the restore: per-session gates are fresh.
        assert session._equity_history == []
        await session.stop()

    @pytest.mark.asyncio
    async def test_state_disabled_default_zero_behavior(self, tmp_path):
        """state.enabled=false -> no state store, no gate, unchanged start."""
        _write_checkpoint(tmp_path)  # checkpoint exists but must be ignored
        session = TradingSession(_make_config(tmp_path, state_enabled=False), strategies=[])
        await session.start(mode="paper")

        assert session._state_store is None
        assert session._recovery_verified is True
        assert session.portfolio.cash == pytest.approx(100_000.0)  # untouched
        assert session.portfolio.get_position("BTC/USDT") is None
        await session.stop()


class TestRecoveryFailClosedGate:
    @pytest.mark.asyncio
    async def test_drift_blocks_buy_but_allows_flat(self, tmp_path):
        """Restored book != exchange (paper gateway book empty) -> BUY blocked
        with reason recovery_unverified; FLAT close still passes (exit-safe)."""
        _write_checkpoint(tmp_path)
        session = TradingSession(_make_config(tmp_path), strategies=[])
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
        await session._process_signal(_buy_signal())
        assert "recovery_unverified" in blocked
        assert session.execution.order_manager.total_orders == 0

        # FLAT is exempt: the close attempt reaches execution (not blocked at
        # the recovery gate). PaperGateway rejects the reduce-only order — its
        # book is empty, which IS the drift under test — but the gate let it
        # through: exactly one order was submitted and no second block fired.
        session.execution.update_market_price("BTC/USDT", 51_000.0)
        await session._process_signal(_flat_signal())
        assert blocked.count("recovery_unverified") == 1  # no second block
        assert session.execution.order_manager.total_orders == 1  # close attempted
        await session.stop()

    @pytest.mark.asyncio
    async def test_verified_recovery_allows_entries(self, tmp_path):
        """Exchange book matches the restore -> verification passes."""
        _write_checkpoint(tmp_path)
        session = TradingSession(_make_config(tmp_path), strategies=[])
        blocked: list[str] = []
        session.event_bus.subscribe(
            EVENT_RISK,
            lambda e: (
                blocked.append(e.data.get("reason", ""))
                if e.data.get("type") == "signal_blocked"
                else None
            ),
        )

        async def matching_positions():
            return [
                Position(
                    symbol="BTC/USDT",
                    quantity=0.5,
                    entry_price=50_000.0,
                    current_price=51_000.0,
                )
            ]

        await session.start(mode="paper")
        # Wire the matching exchange view, then re-verify like a fresh start.
        gateway = session.execution.gateway
        assert gateway is not None
        gateway.query_positions = matching_positions  # type: ignore[method-assign]
        session._recovery_verified = await session._verify_recovery()
        assert session._recovery_verified is True

        session.execution.update_market_price("BTC/USDT", 51_000.0)
        await session._process_signal(_buy_signal())
        assert "recovery_unverified" not in blocked
        await session.stop()

    @pytest.mark.asyncio
    async def test_corrupt_checkpoint_fail_closed(self, tmp_path):
        _write_checkpoint(tmp_path)
        corrupt = tmp_path / "checkpoints" / CHECKPOINT_FILENAME
        corrupt.write_text("{garbage", encoding="utf-8")
        session = TradingSession(_make_config(tmp_path), strategies=[])
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
        await session._process_signal(_buy_signal())
        assert "recovery_unverified" in blocked
        assert session.execution.order_manager.total_orders == 0
        await session.stop()


class TestPeriodicMaintenance:
    @pytest.mark.asyncio
    async def test_checkpoint_save_writes_file(self, tmp_path):
        """_periodic_maintenance saves a checkpoint when due (state.enabled)."""
        session = TradingSession(_make_config(tmp_path), strategies=[])
        await session.start(mode="paper")
        # Force "due" by rewinding the last-save stamp.
        session._last_checkpoint_at = 0.0
        await session._periodic_maintenance()
        assert (tmp_path / "checkpoints" / CHECKPOINT_FILENAME).exists()
        loaded = StateStore(str(tmp_path / "checkpoints")).load_checkpoint()
        assert loaded is not None
        assert loaded.cash == pytest.approx(session.portfolio.cash)
        await session.stop()
