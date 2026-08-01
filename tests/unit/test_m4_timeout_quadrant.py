"""Phase 6 integration test — M4 timeout quadrant decision matrix.

Tests the four-quadrant logic in TradingSession.run_data_loop (engine.py ~L766-788):
  A: cancel=True,  sync=True  → release
  B: cancel=True,  sync=False → release
  C: cancel=False, sync=True  → release
  D: cancel=False, sync=False → HOLD + CRITICAL log
  Legacy (empty sym)           → immediate release
  cancel raises + sync True    → release (C)
  cancel raises + sync False   → HOLD (D)
  sync raises   + cancel True  → release (B)
  D-hold then sync True next cycle → release
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import pytest

from quantflow.common.config import AppConfig
from quantflow.strategy.base import StrategyBase, StrategyContext
from quantflow.strategy.engine import TradingSession


# ---------------------------------------------------------------------------
# Minimal strategy stub required by TradingSession constructor
# ---------------------------------------------------------------------------
class _StubStrategy(StrategyBase):
    name = "stub"

    def on_init(self, ctx: StrategyContext) -> None:
        pass

    def on_bar(self, ctx: StrategyContext, bar: Any) -> None:
        pass

    def generate_signals(self, df: Any) -> tuple[list, list]:
        return ([], [])


# ---------------------------------------------------------------------------
# Helper: build a session wired for the live-fetcher path with all external
# I/O replaced by deterministic fakes.  Returns (session, controls_dict).
# ---------------------------------------------------------------------------
def _make_session(monkeypatch: pytest.MonkeyPatch) -> tuple[TradingSession, dict[str, Any]]:
    session = TradingSession(AppConfig(), [_StubStrategy()])
    session._running = True
    session._config.execution.mode = "live"

    # ---- Fake DataFetcher (always returns empty DataFrame) ----
    class FakeFetcher:
        def __init__(self, _config: object) -> None:
            self.disconnected = False

        async def connect(self) -> None:
            return None

        async def fetch_ohlcv(
            self,
            symbol: str,
            timeframe: str,
            start: object = None,
            limit: int = 10,
        ) -> pd.DataFrame:
            return pd.DataFrame()

        async def disconnect(self) -> None:
            self.disconnected = True

    monkeypatch.setattr(
        "quantflow.data.fetcher.DataFetcher",
        lambda config: FakeFetcher(config),
    )
    monkeypatch.setattr(
        "quantflow.strategy.engine.asyncio.sleep",
        _async_noop,
    )

    # Health check — always healthy
    session.check_health = lambda: {"running": True}

    # Controls dict populated by each test's own closures
    controls: dict[str, Any] = {}
    return session, controls


async def _async_noop(*_args: object, **_kwargs: object) -> None:
    return None


# ---------------------------------------------------------------------------
# Helper: patch check_timeouts / cancel / sync_positions on a session.
#
# check_timeouts is a closure that:
#   - On the FIRST call returns [(oid, sym)] and sets _running=False
#   - On subsequent calls returns []
# This guarantees exactly ONE iteration of the while loop processes the
# timeout entry, then the loop exits naturally.
# ---------------------------------------------------------------------------
def _wire_timeout(
    session: TradingSession,
    *,
    oid: str,
    sym: str,
    cancel_result: bool | Exception,
    sync_result: bool | Exception,
    extra_timeout_calls: list[list[tuple[str, str]]] | None = None,
) -> dict[str, Any]:
    """Wire deterministic timeout path.

    cancel_result / sync_result:
        bool  → return that value
        Exception → raise it when called

    extra_timeout_calls:
        Optional list of additional check_timeouts return values AFTER the
        first call (before setting _running=False).  Used by test 8 to
        simulate a second cycle.
    """
    call_count = [0]
    extra_idx = [0]
    controls: dict[str, Any] = {
        "cancel_calls": [],
        "sync_calls": [],
    }

    def fake_check_timeouts() -> list[tuple[str, str]]:
        call_count[0] += 1
        if call_count[0] == 1:
            return [(oid, sym)]
        # Extra cycles (test 8)
        if extra_timeout_calls and extra_idx[0] < len(extra_timeout_calls):
            result = extra_timeout_calls[extra_idx[0]]
            extra_idx[0] += 1
            return result
        session._running = False
        return []

    async def fake_cancel(o: str, s: str) -> bool:
        controls["cancel_calls"].append((o, s))
        if isinstance(cancel_result, Exception):
            raise cancel_result
        return cancel_result

    async def fake_sync_positions() -> bool:
        controls["sync_calls"].append(True)
        if isinstance(sync_result, Exception):
            raise sync_result
        return sync_result

    session._execution.check_timeouts = fake_check_timeouts  # type: ignore[assignment]
    session._execution.cancel = fake_cancel  # type: ignore[assignment]
    session._execution.sync_positions = fake_sync_positions  # type: ignore[assignment]

    return controls


def _wire_legacy_timeout(
    session: TradingSession,
    *,
    oid: str,
) -> None:
    """Wire check_timeouts to return (oid, '') — empty symbol → legacy path."""
    call_count = [0]

    def fake_check_timeouts() -> list[tuple[str, str]]:
        call_count[0] += 1
        if call_count[0] == 1:
            return [(oid, "")]
        session._running = False
        return []

    session._execution.check_timeouts = fake_check_timeouts  # type: ignore[assignment]


# ===========================================================================
# Tests
# ===========================================================================
class TestM4TimeoutQuadrant:
    """Test the four-quadrant timeout decision matrix in run_data_loop."""

    # --- Quadrant A: cancel=True, sync=True → release ---
    @pytest.mark.asyncio
    async def test_quadrant_a_both_ok_releases(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session, _ = _make_session(monkeypatch)
        oid = "order-A"
        session._portfolio.reserve(oid, "BTC/USDT", 1000.0)

        ctrls = _wire_timeout(
            session, oid=oid, sym="BTC/USDT", cancel_result=True, sync_result=True
        )
        await session.run_data_loop(symbol="BTC/USDT", symbols=["BTC/USDT"])

        assert session._portfolio.total_pending_exposure == 0.0
        assert ctrls["cancel_calls"] == [(oid, "BTC/USDT")]
        assert len(ctrls["sync_calls"]) == 1

    # --- Quadrant B: cancel=True, sync=False → release ---
    @pytest.mark.asyncio
    async def test_quadrant_b_cancel_only_releases(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session, _ = _make_session(monkeypatch)
        oid = "order-B"
        session._portfolio.reserve(oid, "BTC/USDT", 2000.0)

        _wire_timeout(session, oid=oid, sym="BTC/USDT", cancel_result=True, sync_result=False)
        await session.run_data_loop(symbol="BTC/USDT", symbols=["BTC/USDT"])

        assert session._portfolio.total_pending_exposure == 0.0

    # --- Quadrant C: cancel=False, sync=True → release ---
    @pytest.mark.asyncio
    async def test_quadrant_c_sync_only_releases(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session, _ = _make_session(monkeypatch)
        oid = "order-C"
        session._portfolio.reserve(oid, "BTC/USDT", 3000.0)

        _wire_timeout(session, oid=oid, sym="BTC/USDT", cancel_result=False, sync_result=True)
        await session.run_data_loop(symbol="BTC/USDT", symbols=["BTC/USDT"])

        assert session._portfolio.total_pending_exposure == 0.0

    # --- Quadrant D: cancel=False, sync=False → HOLD + CRITICAL log ---
    @pytest.mark.asyncio
    async def test_quadrant_d_both_fail_holds(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        session, _ = _make_session(monkeypatch)
        oid = "order-D"
        session._portfolio.reserve(oid, "BTC/USDT", 4000.0)

        _wire_timeout(session, oid=oid, sym="BTC/USDT", cancel_result=False, sync_result=False)

        with caplog.at_level(logging.CRITICAL, logger="quantflow.strategy.engine"):
            await session.run_data_loop(symbol="BTC/USDT", symbols=["BTC/USDT"])

        # Pending is HELD (Fail-Closed)
        assert session._portfolio.total_pending_exposure == 4000.0
        # CRITICAL log emitted
        assert any("pending HELD" in r.message for r in caplog.records)

    # --- Legacy: empty symbol → immediate release ---
    @pytest.mark.asyncio
    async def test_legacy_empty_symbol_immediate_release(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session, _ = _make_session(monkeypatch)
        oid = "order-legacy"
        session._portfolio.reserve(oid, "BTC/USDT", 5000.0)

        _wire_legacy_timeout(session, oid=oid)
        await session.run_data_loop(symbol="BTC/USDT", symbols=["BTC/USDT"])

        assert session._portfolio.total_pending_exposure == 0.0

    # --- cancel raises + sync=True → release (effectively quadrant C) ---
    @pytest.mark.asyncio
    async def test_cancel_raises_sync_ok_releases(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session, _ = _make_session(monkeypatch)
        oid = "order-CE"
        session._portfolio.reserve(oid, "BTC/USDT", 6000.0)

        _wire_timeout(
            session,
            oid=oid,
            sym="BTC/USDT",
            cancel_result=RuntimeError("exchange down"),
            sync_result=True,
        )
        await session.run_data_loop(symbol="BTC/USDT", symbols=["BTC/USDT"])

        assert session._portfolio.total_pending_exposure == 0.0

    # --- cancel raises + sync=False → HOLD (effectively quadrant D) ---
    @pytest.mark.asyncio
    async def test_cancel_raises_sync_fail_holds(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        session, _ = _make_session(monkeypatch)
        oid = "order-DE"
        session._portfolio.reserve(oid, "BTC/USDT", 7000.0)

        _wire_timeout(
            session,
            oid=oid,
            sym="BTC/USDT",
            cancel_result=RuntimeError("exchange down"),
            sync_result=False,
        )
        with caplog.at_level(logging.CRITICAL, logger="quantflow.strategy.engine"):
            await session.run_data_loop(symbol="BTC/USDT", symbols=["BTC/USDT"])

        assert session._portfolio.total_pending_exposure == 7000.0
        assert any("pending HELD" in r.message for r in caplog.records)

    # --- sync_positions raises + cancel=True → release (effectively quadrant B) ---
    @pytest.mark.asyncio
    async def test_sync_raises_cancel_ok_releases(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session, _ = _make_session(monkeypatch)
        oid = "order-SR"
        session._portfolio.reserve(oid, "BTC/USDT", 8000.0)

        _wire_timeout(
            session,
            oid=oid,
            sym="BTC/USDT",
            cancel_result=True,
            sync_result=RuntimeError("sync boom"),
        )
        await session.run_data_loop(symbol="BTC/USDT", symbols=["BTC/USDT"])

        assert session._portfolio.total_pending_exposure == 0.0

    # --- Interaction: D-hold on cycle 1, then sync=True on cycle 2 → release ---
    @pytest.mark.asyncio
    async def test_d_hold_then_sync_ok_next_cycle_releases(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session, _ = _make_session(monkeypatch)
        oid = "order-D2"
        session._portfolio.reserve(oid, "BTC/USDT", 9000.0)

        # Cycle 1: D-hold.  Cycle 2: re-emit same oid with sync=True → release.
        # We use a mutable state so cancel/sync change between cycles.
        cycle = [0]

        call_count = [0]

        def fake_check_timeouts() -> list[tuple[str, str]]:
            call_count[0] += 1
            if call_count[0] == 1:
                return [(oid, "BTC/USDT")]
            if call_count[0] == 2:
                return [(oid, "BTC/USDT")]
            session._running = False
            return []

        async def fake_cancel(o: str, s: str) -> bool:
            cycle[0] += 1
            return False  # always fail cancel

        sync_call_count = [0]

        async def fake_sync() -> bool:
            sync_call_count[0] += 1
            # First cycle: sync fails.  Second cycle: sync succeeds.
            return sync_call_count[0] > 1

        session._execution.check_timeouts = fake_check_timeouts  # type: ignore[assignment]
        session._execution.cancel = fake_cancel  # type: ignore[assignment]
        session._execution.sync_positions = fake_sync  # type: ignore[assignment]

        await session.run_data_loop(symbol="BTC/USDT", symbols=["BTC/USDT"])

        # After cycle 2, pending should be released
        assert session._portfolio.total_pending_exposure == 0.0
        assert sync_call_count[0] == 2
