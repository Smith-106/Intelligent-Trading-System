"""Coverage completion tests for quantflow/strategy/engine.py.

Drives the previously-uncovered line/branch groups: module helpers, start()
checkpoint restore / background-task flags, s5 symbol/strategy rebalance
attribution, signal processing edge branches (recovery-unverified, risk
pause, order statuses, submit failure), crash-recovery helpers, meta/BBO
feed loops, and the presentation facade.

All tests use mocks for external components (execution gateway, fetchers,
sinks, state store) per the project's unit-test convention.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from quantflow.common.config import AppConfig
from quantflow.common.models import (
    Bar,
    Direction,
    Order,
    OrderSide,
    OrderStatus,
    RiskDecision,
    Signal,
)
from quantflow.execution.state_store import SessionSnapshot
from quantflow.strategy.base import StrategyBase
from quantflow.strategy.engine import (
    TradingSession,
    _ensure_metrics_server_started,
    _weekly_base_equity,
)


def _make_bar(price: float = 100.0, idx: int = 0, symbol: str = "BTC/USDT") -> Bar:
    return Bar(
        symbol, 1700000000 + idx * 60000, price - 0.5, price + 1.0, price - 1.0, price, 1000.0
    )


def _signal(symbol: str = "BTC/USDT", direction: Direction = Direction.LONG) -> Signal:
    return Signal(
        symbol=symbol,
        direction=direction,
        strength=0.8,
        price=100.0,
        strategy_id="probe",
    )


class _NoopStrategy(StrategyBase):
    def __init__(self, name: str = "noop") -> None:
        super().__init__(name=name)

    def on_init(self, ctx) -> None:  # type: ignore[override]
        pass

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        entries = pd.Series(False, index=df.index)
        return entries, entries


class TestModuleHelpers:
    def test_ensure_metrics_server_started_noop(self) -> None:
        """L57-59: deprecated shim is a no-op."""
        assert _ensure_metrics_server_started(9099) is None

    def test_weekly_base_equity_fallback_to_newest(self) -> None:
        """L99: all history older than the week window → newest snapshot fallback."""
        history = [(1, 100.0), (2, 101.0)]
        base_equity, idx, _ = _weekly_base_equity(history, 0, 10**12)
        assert base_equity == 101.0
        assert idx == 2

class TestBookRiskBudgetConstruction:
    def test_enabled_builds_book_budget(self) -> None:
        """L155-157: config.risk.book_risk_budget.enabled → BookRiskBudget wired."""
        cfg = AppConfig()
        cfg.risk.book_risk_budget.enabled = True
        session = TradingSession(cfg, [])
        assert session._risk_engine._book_risk_budget is not None


class TestStartCheckpointRestore:
    @pytest.mark.asyncio
    async def test_restore_snapshot_and_verify(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L377-387: state.enabled + checkpoint → restore + verify + info log."""
        cfg = AppConfig()
        cfg.state.enabled = True
        cfg.state.checkpoint_dir = "./data/checkpoints-test-restore"
        session = TradingSession(cfg, [])
        snapshot = SessionSnapshot(
            saved_at_ms=1,
            mode="paper",
            cash=120000.0,
            positions=[{"symbol": "BTC/USDT", "quantity": 1.0, "entry_price": 90.0}],
            open_orders=[],
            equity=130000.0,
        )
        fake_store = MagicMock()
        fake_store.load_checkpoint.return_value = snapshot

        with (
            patch("quantflow.strategy.engine.StateStore", return_value=fake_store),
            patch.object(session._execution, "start", new_callable=AsyncMock),
            patch.object(session, "_verify_recovery", new_callable=AsyncMock) as mock_verify,
        ):
            mock_verify.return_value = True
            await session.start(mode="paper")

        assert session._recovery_verified is True
        # cash delta restored: 120000 - 100000 = +20000
        assert session._portfolio.cash == pytest.approx(120000.0)
        pos = session._portfolio.get_position("BTC/USDT")
        assert pos is not None and pos.quantity == 1.0

    @pytest.mark.asyncio
    async def test_corrupt_checkpoint_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L388-392: load_checkpoint None + last_error → entries blocked."""
        cfg = AppConfig()
        cfg.state.enabled = True
        session = TradingSession(cfg, [])
        fake_store = MagicMock()
        fake_store.load_checkpoint.return_value = None
        fake_store.last_error = "corrupt json"

        with (
            patch("quantflow.strategy.engine.StateStore", return_value=fake_store),
            patch.object(session._execution, "start", new_callable=AsyncMock),
        ):
            await session.start(mode="paper")

        assert session._recovery_verified is False

    @pytest.mark.asyncio
    async def test_reconciliation_engine_built_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L393-395 + L1007-1011: reconciliation.enabled → engine constructed."""
        cfg = AppConfig()
        cfg.reconciliation.enabled = True
        session = TradingSession(cfg, [])
        session._execution._gateway = MagicMock()

        with (
            patch.object(session._execution, "start", new_callable=AsyncMock),
            patch(
                "quantflow.strategy.engine.ReconciliationEngine",
                return_value=MagicMock(),
            ),
        ):
            await session.start(mode="paper")

        assert session._reconciliation_engine is not None


class TestStartBackgroundFlags:
    @pytest.mark.asyncio
    async def test_funding_bbo_trades_flags_spawn_tasks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L447-456: opt-in feed/ingest tasks spawned when enabled (no symbols → idle)."""
        cfg = AppConfig()
        cfg.execution.funding_feed_enabled = True
        cfg.execution.bbo_poll_enabled = True
        cfg.execution.trades_poll_enabled = True
        session = TradingSession(cfg, [])
        with (
            patch.object(session._execution, "start", new_callable=AsyncMock),
            patch.object(session._execution, "stop", new_callable=AsyncMock),
            patch.object(session, "_start_trades_ingest", new_callable=MagicMock) as mock_trades,
        ):
            await session.start(mode="paper")
            assert session._meta_feed_task is not None
            assert session._bbo_poll_task is not None
            mock_trades.assert_called_once()
            session._running = False
            await session.stop()


class TestBboSourceAndTicker:
    def test_set_bbo_source_invalid_raises(self) -> None:
        """L468: invalid bbo_source → ValueError."""
        session = TradingSession(AppConfig(), [])
        with pytest.raises(ValueError, match="bbo_source"):
            session.set_bbo_source("bogus")

    def test_push_ticker_bbo_ignores_invalid(self) -> None:
        """L476-479: non-numeric / non-positive / crossed quotes are no-ops."""
        session = TradingSession(AppConfig(), [])
        session._execution.update_orderbook = MagicMock()
        session.push_ticker_bbo("BTC/USDT", "bad", 1.0)
        session.push_ticker_bbo("BTC/USDT", 0.0, 1.0)
        session.push_ticker_bbo("BTC/USDT", 2.0, 1.0)
        session._execution.update_orderbook.assert_not_called()
        assert "BTC/USDT" not in session._ticker_bbo

    def test_push_ticker_bbo_valid_bar_proxy_source(self) -> None:
        """L480-483: valid quote cached; no orderbook forward under bar_proxy."""
        session = TradingSession(AppConfig(), [])
        session._execution.update_orderbook = MagicMock()
        session.push_ticker_bbo("BTC/USDT", 99.0, 101.0)
        assert session._ticker_bbo["BTC/USDT"] == (99.0, 101.0)
        session._execution.update_orderbook.assert_not_called()

    def test_push_ticker_bbo_valid_ticker_source_forwards(self) -> None:
        """L482-483: ticker source forwards fresh quote to execution."""
        session = TradingSession(AppConfig(), [])
        session._execution.update_orderbook = MagicMock()
        session.set_bbo_source("ticker")
        session.push_ticker_bbo("BTC/USDT", 99.0, 101.0)
        session._execution.update_orderbook.assert_called_once_with(
            "BTC/USDT", bid=99.0, ask=101.0, mid_to_last=False
        )


class TestOnBarPortfolioOptimization:
    def _cfg(self, level: str, rebalance: int, enabled: bool = True) -> AppConfig:
        cfg = AppConfig()
        cfg.risk.portfolio_optimization.enabled = enabled
        cfg.risk.portfolio_optimization.level = level
        cfg.risk.portfolio_optimization.rebalance_every_n_bars = rebalance
        cfg.risk.portfolio_optimization.min_samples = 2
        return cfg

    def _session(self, cfg: AppConfig):
        session = TradingSession(cfg, [])
        session._running = True
        session._sink = MagicMock()
        return session

    @pytest.mark.asyncio
    async def test_symbol_level_same_ts_no_rebalance(self) -> None:
        """L582: repeated timestamp → should_rebalance = False."""
        session = self._session(self._cfg("symbol", 1))
        session._portfolio_optimizer.compute = MagicMock(return_value={"BTC/USDT": 1.0})
        with (
            patch.object(session, "_update_portfolio_observability"),
            patch.object(session, "_record_bar_latency"),
        ):
            await session.on_bar(_make_bar(price=100.0, idx=0))
            await session.on_bar(_make_bar(price=100.0, idx=0))  # same ts
        assert session._rebalance_ts_count == 1
        session._sink.record_portfolio_allocation.assert_not_called()

    @pytest.mark.asyncio
    async def test_symbol_level_rebalance_sink_error(self) -> None:
        """L583-592: rebalance path + best-effort sink failure."""
        session = self._session(self._cfg("symbol", 1))
        session._portfolio_optimizer.compute = MagicMock(return_value={"BTC/USDT": 1.0})
        session._sink.record_portfolio_allocation.side_effect = Exception("sink down")
        with (
            patch.object(session, "_update_portfolio_observability"),
            patch.object(session, "_record_bar_latency"),
        ):
            await session.on_bar(_make_bar(price=100.0, idx=1))
            await session.on_bar(_make_bar(price=110.0, idx=2))
        # Sink raised → swallowed (no exception propagated), allocation was set.
        assert session._portfolio.symbol_allocation.get("BTC/USDT") == 1.0

    @pytest.mark.asyncio
    async def test_strategy_level_attribution_and_sink_error(self) -> None:
        """L598-608 + L622-623: per-strategy notional attribution + rebalance sink error."""
        session = self._session(self._cfg("strategy", 100))
        session._portfolio_optimizer.compute = MagicMock(return_value={"a": 0.5, "b": 0.5})
        # Compound strategy id position + a zero-current-price position (skipped).
        session._portfolio.update_position("BTC/USDT", 1.0, 100.0, strategy_id="a,b")
        session._portfolio.positions["ETH/USDT"] = session._portfolio.positions.pop("ETH/USDT") if "ETH/USDT" in session._portfolio.positions else None
        session._portfolio.set_position("ETH/USDT", __import__("quantflow.common.models", fromlist=["Position"]).Position(
            symbol="ETH/USDT", quantity=2.0, entry_price=1.0, current_price=0.0, strategy_id="z"
        ))
        with (
            patch.object(session, "_update_portfolio_observability"),
            patch.object(session, "_record_bar_latency"),
        ):
            for i in range(3):
                await session.on_bar(_make_bar(price=100.0 + i, idx=i))
        # Attribution recorded for compound constituents a and b.
        rets = session._portfolio.get_strategy_returns()
        assert "a" in rets and "b" in rets
        # Fire rebalance + sink failure on the strategy-level path.
        session2 = self._session(self._cfg("strategy", 1))
        session2._portfolio_optimizer.compute = MagicMock(return_value={"a": 1.0})
        session2._sink.record_portfolio_allocation.side_effect = Exception("sink down")
        with (
            patch.object(session2, "_update_portfolio_observability"),
            patch.object(session2, "_record_bar_latency"),
        ):
            await session2.on_bar(_make_bar(price=100.0, idx=1))
            await session2.on_bar(_make_bar(price=101.0, idx=2))
        assert session2._portfolio.allocation.get("a") == 1.0

    @pytest.mark.asyncio
    async def test_equity_history_eviction(self) -> None:
        """L640-642: history cap eviction + weekly-base pointer decrement."""
        session = self._session(AppConfig())
        session._equity_history_maxlen = 2
        session._weekly_base_idx = 1
        with (
            patch.object(session, "_update_portfolio_observability"),
            patch.object(session, "_record_bar_latency"),
        ):
            for i in range(4):
                await session.on_bar(_make_bar(price=100.0 + i, idx=i))
        assert len(session._equity_history) == 2
        assert session._weekly_base_idx == 0

    @pytest.mark.asyncio
    async def test_on_bar_missing_instance_continues(self) -> None:
        """L705: multi-symbol declared but instance absent → skip strategy."""
        cfg = AppConfig()
        session = TradingSession(cfg, [_NoopStrategy("s1")])
        session._running = True
        session._symbols = ["BTC/USDT"]
        session._instances = {}
        session._contexts = {}
        with (
            patch.object(session, "_update_portfolio_observability"),
            patch.object(session, "_record_bar_latency"),
        ):
            await session.on_bar(_make_bar())  # must not raise
        assert True


class TestProcessSignalEdgeBranches:
    @staticmethod
    def _ready_session():
        session = TradingSession(AppConfig(), [])
        session._risk_engine.check = MagicMock(return_value=RiskDecision(passed=True))
        session._position_sizer.size = MagicMock(return_value=1500.0)
        session._execution.submit_order = AsyncMock()
        session._event_bus.publish = MagicMock()
        session._record_signal_latency = MagicMock()
        session._update_portfolio_observability = MagicMock()
        return session

    @pytest.mark.asyncio
    async def test_recovery_unverified_blocks_signal(self) -> None:
        """L765-777: recovery_unverified → new entries blocked."""
        session = self._ready_session()
        session._recovery_verified = False
        await session._process_signal_inner(_signal())
        events = [c.args[0].data for c in session._event_bus.publish.call_args_list]
        assert any(e.get("type") == "signal_blocked" for e in events)

    @pytest.mark.asyncio
    async def test_risk_pause_blocks_signal(self) -> None:
        """L781-798: active risk pause reason → blocked."""
        session = self._ready_session()
        session._risk_pauses.add("funding_risk_gate")
        await session._process_signal_inner(_signal())
        events = [c.args[0].data for c in session._event_bus.publish.call_args_list]
        assert any(e.get("reason", "").startswith("risk_pause:") for e in events)

    @pytest.mark.asyncio
    async def test_submit_order_exception_releases(self) -> None:
        """L886-889: gateway exception → reservation released + re-raised."""
        session = self._ready_session()
        session._execution.submit_order.side_effect = Exception("gateway down")
        with pytest.raises(Exception, match="gateway down"):
            await session._process_signal_inner(_signal())
        assert session._portfolio.total_pending_exposure == 0.0

    @pytest.mark.asyncio
    async def test_partial_fill_partial_confirm(self) -> None:
        """L901-902: PARTIAL order → partial_confirm with cumulative notional."""
        session = self._ready_session()
        session._execution.submit_order.return_value = Order(
            order_id="o1",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=15.0,
            status=OrderStatus.PARTIAL,
            filled_quantity=10.0,
            filled_price=100.0,
        )
        await session._process_signal_inner(_signal())
        # reserved 1500, cumulative fill 1000 → 500 remaining pending.
        assert session._portfolio.total_pending_exposure == pytest.approx(500.0)

    @pytest.mark.asyncio
    async def test_rejected_order_releases(self) -> None:
        """L904: REJECTED order → reservation released."""
        session = self._ready_session()
        session._execution.submit_order.return_value = Order(
            order_id="o1",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=15.0,
            status=OrderStatus.REJECTED,
        )
        await session._process_signal_inner(_signal())
        assert session._portfolio.total_pending_exposure == 0.0

    @pytest.mark.asyncio
    async def test_flat_signal_no_position_noop(self) -> None:
        """L918: FLAT close with no held position → early return."""
        session = self._ready_session()
        await session._process_signal_inner(
            _signal(direction=Direction.FLAT)
        )
        session._execution.submit_order.assert_not_awaited()


class TestCrashRecoveryHelpers:
    def test_restore_from_snapshot(self) -> None:
        """L986-993: cash delta + positions restored; empty symbol skipped."""
        session = TradingSession(AppConfig(), [])
        snapshot = SessionSnapshot(
            saved_at_ms=1,
            mode="paper",
            cash=90000.0,
            positions=[
                {"symbol": "", "quantity": 5.0},
                {"symbol": "BTC/USDT", "quantity": 2.0, "entry_price": 90.0, "current_price": 91.0, "unrealized_pnl": 2.0, "strategy_id": "s1"},
            ],
            open_orders=[],
            equity=95000.0,
        )
        session._restore_from_snapshot(snapshot)
        assert session._portfolio.cash == pytest.approx(90000.0)
        pos = session._portfolio.get_position("BTC/USDT")
        assert pos is not None and pos.quantity == 2.0 and pos.entry_price == 90.0

    def test_build_reconciliation_engine_no_gateway(self) -> None:
        """L1007-1010: gateway unavailable → warning, engine stays None."""
        session = TradingSession(AppConfig(), [])
        session._execution._gateway = None
        session._build_reconciliation_engine()
        assert session._reconciliation_engine is None

    def test_build_reconciliation_engine_built(self) -> None:
        """L1011: gateway present → engine constructed."""
        session = TradingSession(AppConfig(), [])
        session._execution._gateway = MagicMock()
        with patch("quantflow.strategy.engine.ReconciliationEngine", return_value=MagicMock()):
            session._build_reconciliation_engine()
        assert session._reconciliation_engine is not None

    @pytest.mark.asyncio
    async def test_verify_recovery_branches(self) -> None:
        """L1026-1044: all fail-closed outcomes + success."""
        session = TradingSession(AppConfig(), [])
        session._build_reconciliation_engine = MagicMock()

        # engine None → False
        session._reconciliation_engine = None
        assert await session._verify_recovery() is False

        # exception → False
        engine = MagicMock()
        engine.run_daily_reconciliation = AsyncMock(side_effect=Exception("boom"))
        session._reconciliation_engine = engine
        assert await session._verify_recovery() is False

        # non-completed status → False
        engine = MagicMock()
        engine.run_daily_reconciliation = AsyncMock(
            return_value=SimpleNamespace(status="error", error_message="x", discrepancies=SimpleNamespace(total_discrepancies=0))
        )
        session._reconciliation_engine = engine
        assert await session._verify_recovery() is False

        # discrepancies → False
        engine = MagicMock()
        engine.run_daily_reconciliation = AsyncMock(
            return_value=SimpleNamespace(status="completed", error_message="", discrepancies=SimpleNamespace(total_discrepancies=2))
        )
        session._reconciliation_engine = engine
        assert await session._verify_recovery() is False

        # ok → True
        engine = MagicMock()
        engine.run_daily_reconciliation = AsyncMock(
            return_value=SimpleNamespace(status="completed", error_message="", discrepancies=SimpleNamespace(total_discrepancies=0))
        )
        session._reconciliation_engine = engine
        assert await session._verify_recovery() is True

    def test_build_snapshot(self) -> None:
        """L1048-1072: positions + open orders snapshot."""
        session = TradingSession(AppConfig(), [])
        session._portfolio.update_position("BTC/USDT", 1.0, 100.0, strategy_id="s1")
        fake_order = Order(
            order_id="o1", symbol="BTC/USDT", side=OrderSide.BUY, order_type="market",
            quantity=1.0, price=100.0, status=OrderStatus.SUBMITTED, strategy_id="s1",
        )
        session._execution.order_manager.get_open_orders = MagicMock(return_value=[fake_order])
        snap = session._build_snapshot()
        assert len(snap.positions) == 1
        assert snap.positions[0]["symbol"] == "BTC/USDT"
        assert len(snap.open_orders) == 1
        assert snap.open_orders[0]["status"] == OrderStatus.SUBMITTED.value

    @pytest.mark.asyncio
    async def test_periodic_maintenance_and_exceptions(self) -> None:
        """L1095-1110: recon + checkpoint duties with failure isolation."""
        cfg = AppConfig()
        cfg.reconciliation.enabled = True
        cfg.state.enabled = True
        session = TradingSession(cfg, [])
        recon = MagicMock()
        recon.run_daily_reconciliation = AsyncMock()
        session._reconciliation_engine = recon
        store = MagicMock()
        store.save_checkpoint = MagicMock()
        session._state_store = store
        session._last_reconciliation_at = 0.0
        session._last_checkpoint_at = 0.0
        await session._periodic_maintenance()
        recon.run_daily_reconciliation.assert_awaited_once()
        store.save_checkpoint.assert_called_once()

        # failures swallowed
        recon2 = MagicMock()
        recon2.run_daily_reconciliation = AsyncMock(side_effect=Exception("recon fail"))
        session._reconciliation_engine = recon2
        store2 = MagicMock()
        store2.save_checkpoint = MagicMock(side_effect=Exception("save fail"))
        session._state_store = store2
        session._last_reconciliation_at = 0.0
        session._last_checkpoint_at = 0.0
        await session._periodic_maintenance()  # must not raise
        assert True


class TestKolReferenceMultiplier:
    def test_enabled_returns_multiplier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L1132-1153: enabled KOL consensus → multiplier applied."""
        cfg = AppConfig()
        cfg.kol_reference.enabled = True
        session = TradingSession(cfg, [])
        monkeypatch.setattr(
            "quantflow.strategy.kol_signals.reference_weight.reference_multiplier",
            lambda *a, **k: SimpleNamespace(multiplier=1.1),
        )
        assert session._kol_reference_multiplier(_signal()) == pytest.approx(1.1)

    def test_exception_falls_back_to_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L1154-1155: any failure → 1.0 fail-soft."""
        cfg = AppConfig()
        cfg.kol_reference.enabled = True
        session = TradingSession(cfg, [])
        def _boom(*a, **k):
            raise RuntimeError("no consensus file")
        monkeypatch.setattr(
            "quantflow.strategy.kol_signals.reference_weight.reference_multiplier", _boom
        )
        assert session._kol_reference_multiplier(_signal()) == 1.0

    def test_disabled_returns_one(self) -> None:
        """kol disabled → 1.0 (local import path)."""
        session = TradingSession(AppConfig(), [])
        assert session._kol_reference_multiplier(_signal()) == 1.0


class TestTradesIngest:
    @pytest.mark.asyncio
    async def test_start_trades_ingest_no_symbols(self, caplog: pytest.LogCaptureFixture) -> None:
        """L1176-1178: no symbols → idle warning."""
        session = TradingSession(AppConfig(), [])
        session._symbols = []
        with patch("quantflow.data.trades_ingest.TradesIngestLoop"), patch(
            "quantflow.data.trades_store.TradesStore"
        ):
            session._start_trades_ingest()
        assert session._trades_ingest is None

    @pytest.mark.asyncio
    async def test_start_trades_ingest_injected_fetcher(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L1184-1208: injected fetcher with fetch_trades → loop started."""
        session = TradingSession(AppConfig(), [])
        session._symbols = ["BTC/USDT"]
        session._trades_fetcher = MagicMock(fetch_trades=AsyncMock())
        fake_loop = MagicMock()
        fake_store = MagicMock()
        with (
            patch("quantflow.data.trades_ingest.TradesIngestLoop", return_value=fake_loop),
            patch("quantflow.data.trades_store.TradesStore", return_value=fake_store),
            patch("quantflow.data.trades_ingest.make_fetcher_adapter", return_value=lambda sym: None),
        ):
            session._start_trades_ingest()
        fake_loop.start.assert_called_once()
        assert session._trades_ingest is fake_loop

    @pytest.mark.asyncio
    async def test_start_trades_ingest_creates_fetcher(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L1187-1197: no injected fetcher → DataFetcher built + connect task."""
        session = TradingSession(AppConfig(), [])
        session._symbols = ["BTC/USDT"]
        session._trades_fetcher = None
        fake_fetcher = MagicMock()
        fake_fetcher.fetch_trades = AsyncMock()
        fake_loop = MagicMock()
        with (
            patch("quantflow.data.trades_ingest.TradesIngestLoop", return_value=fake_loop),
            patch("quantflow.data.trades_store.TradesStore", return_value=MagicMock()),
            patch("quantflow.data.fetcher.DataFetcher", return_value=fake_fetcher),
            patch("asyncio.create_task", return_value=MagicMock()),
        ):
            session._start_trades_ingest()
        fake_loop.start.assert_called_once()
        assert session._trades_fetcher is fake_fetcher


class TestBboPollLoop:
    @pytest.mark.asyncio
    async def test_no_symbols_idle(self) -> None:
        """L1226-1227: no symbols → idle."""
        session = TradingSession(AppConfig(), [])
        session._running = True
        await session._bbo_poll_loop()

    @pytest.mark.asyncio
    async def test_injected_fetcher_no_disconnect(self) -> None:
        """L1259-1261: cancellation path via CancelledError."""
        cfg = AppConfig()
        cfg.execution.bbo_poll_interval_s = 1.0
        session = TradingSession(cfg, [])
        session._symbols = ["BTC/USDT"]
        fake = MagicMock()
        fake.fetch_ticker = AsyncMock(return_value={"bid": 1.0, "ask": 2.0})
        session._bbo_fetcher = fake
        session._running = True
        with (
            patch("asyncio.sleep", side_effect=asyncio.CancelledError),
            pytest.raises(asyncio.CancelledError),
        ):
            await session._bbo_poll_loop()


class TestMetaFeed:
    @pytest.mark.asyncio
    async def test_meta_feed_loop_idle_no_symbols(self) -> None:
        """L1276-1279: no symbols → idle."""
        session = TradingSession(AppConfig(), [])
        session._running = True
        await session._meta_feed_loop()

    @pytest.mark.asyncio
    async def test_meta_feed_loop_connect_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L1281-1311: fetcher/dq built, connect fail tolerated, loop cycles."""
        session = TradingSession(AppConfig(), [])
        session._symbols = ["BTC/USDT"]
        fake_fetcher = MagicMock()
        fake_fetcher.connect = AsyncMock(side_effect=Exception("connect fail"))
        fake_dq = MagicMock()
        with (
            patch("quantflow.data.market_meta_fetcher.MarketMetaFetcher", return_value=fake_fetcher),
            patch("quantflow.data.dq_monitor.DataQualityMonitor", return_value=fake_dq),
            patch.object(session, "_meta_poll_funding", new_callable=AsyncMock),
            patch.object(session, "_meta_poll_oi", new_callable=AsyncMock),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            async def _stop_after_sleep(*a, **k):
                session._running = False
            mock_sleep.side_effect = _stop_after_sleep
            session._running = True
            await session._meta_feed_loop()
        assert session._meta_fetcher is fake_fetcher
        assert session._dq_monitor is fake_dq

    @pytest.mark.asyncio
    async def test_meta_feed_loop_cancelled(self) -> None:
        """L1309-1311: CancelledError propagates."""
        session = TradingSession(AppConfig(), [])
        session._symbols = ["BTC/USDT"]
        session._meta_fetcher = MagicMock()
        session._meta_fetcher.connect = AsyncMock()
        session._dq_monitor = MagicMock()
        session._running = True
        with (
            patch.object(session, "_meta_poll_funding", new_callable=AsyncMock),
            patch.object(session, "_meta_poll_oi", new_callable=AsyncMock),
            patch("asyncio.sleep", side_effect=asyncio.CancelledError),
            pytest.raises(asyncio.CancelledError),
        ):
            await session._meta_feed_loop()

    @staticmethod
    def _snap(rate: float = 0.0005, oi: float = 1000.0):
        return SimpleNamespace(
            fetched_at_ms=1700000000000,
            settlement_interval_ms=3600000,
            funding_rate=rate,
            open_interest=oi,
        )

class TestFundingRiskGate:
    @pytest.mark.asyncio
    async def test_disabled_noop_and_blocked_kill(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L1382-1404: disabled no-op; blocked + kill → kill-switch task."""
        cfg = AppConfig()
        session = TradingSession(cfg, [])
        session.note_funding_rate("BTC/USDT", 0.005)  # disabled → no pause
        assert "funding_risk_gate" not in session._risk_pauses.reasons

        cfg2 = AppConfig()
        cfg2.risk.funding_risk_gate_enabled = True
        cfg2.risk.funding_risk_gate_kill = True
        cfg2.risk.max_funding_rate_abs = 0.001
        session2 = TradingSession(cfg2, [])
        kill = MagicMock()
        kill.is_active = False
        kill.activate = AsyncMock()
        session2._kill_switch = kill
        session2._event_bus.publish = MagicMock()
        with patch("asyncio.create_task", return_value=MagicMock()) as mock_task:
            session2.note_funding_rate("BTC/USDT", 0.005)
            mock_task.assert_called_once()
        assert "funding_risk_gate" in session2._risk_pauses.reasons

    @pytest.mark.asyncio
    async def test_blocked_then_clear(self) -> None:
        """L1384-1406: gate blocks then clears on recovery."""
        cfg = AppConfig()
        cfg.risk.funding_risk_gate_enabled = True
        cfg.risk.max_funding_rate_abs = 0.001
        session = TradingSession(cfg, [])
        session.note_funding_rate("BTC/USDT", 0.005)
        assert "funding_risk_gate" in session._risk_pauses.reasons
        session.note_funding_rate("BTC/USDT", 0.0001)
        assert "funding_risk_gate" not in session._risk_pauses.reasons


class TestMetaFreshness:
    def test_meta_data_fresh_all_branches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L1460-1471: fail-closed freshness checks."""
        session = TradingSession(AppConfig(), [])
        now_ms = 1_800_000_000_000
        monkeypatch.setattr("quantflow.strategy.engine.time.time", lambda: now_ms / 1000.0)
        assert session._meta_data_fresh("MISSING") is False
        session._meta_fresh["A"] = {"funding": False, "oi": True}
        assert session._meta_fresh and session._meta_data_fresh("A") is False
        session._meta_fresh["B"] = {"funding": True, "oi": False}
        assert session._meta_data_fresh("B") is False
        session._meta_fresh["C"] = {"funding": True, "oi": True, "settled_interval_ms": 0}
        assert session._meta_data_fresh("C") is False
        session._meta_fresh["D"] = {
            "funding": True, "oi": True, "settled_interval_ms": 3600000,
            "funding_at_ms": now_ms - 3 * 3600000,  # stale (>2x interval)
            "oi_at_ms": now_ms - 500000,
        }
        assert session._meta_data_fresh("D") is False
        session._meta_fresh["E"] = {
            "funding": True, "oi": True, "settled_interval_ms": 3600000,
            "funding_at_ms": now_ms - 3600000,
            "oi_at_ms": now_ms - 700000,  # OI stale >600s
        }
        assert session._meta_data_fresh("E") is False
        session._meta_fresh["F"] = {
            "funding": True, "oi": True, "settled_interval_ms": 3600000,
            "funding_at_ms": now_ms - 3600000,
            "oi_at_ms": now_ms - 100000,
        }
        assert session._meta_data_fresh("F") is True

    def test_apply_meta_freshness_variants(self) -> None:
        """L1475-1482: gating push per strategy name / setter availability."""
        cfg = AppConfig()
        cfg.execution.funding_feed_enabled = True
        session = TradingSession(cfg, [])
        # strategy != funding_rate → no-op
        session._apply_meta_freshness("other", "BTC/USDT", object())
        # funding_rate with mock setter
        inst = MagicMock()
        session._apply_meta_freshness("funding_rate", "BTC/USDT", inst)
        inst.set_freshness_gate.assert_called_once()
        # no setter → no-op
        inst2 = object()
        session._apply_meta_freshness("funding_rate", "BTC/USDT", inst2)
        assert True


class TestRunDataLoop:
    @pytest.mark.asyncio
    async def test_no_symbols_raises(self) -> None:
        """L1515: no symbols anywhere → ValueError."""
        session = TradingSession(AppConfig(), [])
        with pytest.raises(ValueError, match="No symbols"):
            await session.run_data_loop()

    @pytest.mark.asyncio
    async def test_stale_pending_sweep_alert(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L1651-1656: stale pending sweep → critical alert."""
        cfg = AppConfig()
        cfg.execution.mode = "live"
        session = TradingSession(cfg, [])
        session._sink.send_alert = AsyncMock()
        fake_fetcher = MagicMock()
        fake_fetcher.connect = AsyncMock()
        fake_fetcher.fetch_ohlcv = AsyncMock(return_value=pd.DataFrame())
        fake_fetcher.disconnect = AsyncMock()
        session._portfolio.sweep_stale_pending = MagicMock(return_value=["oid1"])
        with (
            patch("quantflow.data.fetcher.DataFetcher", return_value=fake_fetcher),
            patch.object(session._execution, "check_timeouts", return_value=[]),
            patch.object(session, "check_health"),
            patch.object(session, "_periodic_maintenance", new_callable=AsyncMock),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            async def _stop_after_sleep(*a, **k):
                session._running = False
            mock_sleep.side_effect = _stop_after_sleep
            session._running = True
            await session.run_data_loop(
                symbol="BTC/USDT", timeframe="1h", interval_seconds=60
            )
        session._sink.send_alert.assert_awaited_once()


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_drains_tasks_and_ingest(self) -> None:
        """L1759-1772: drain meta/BBO tasks + trades ingest + execution stop."""
        session = TradingSession(AppConfig(), [])
        session._execution.stop = AsyncMock()
        meta_task = asyncio.create_task(asyncio.sleep(3600))
        bbo_task = asyncio.create_task(asyncio.sleep(3600))
        session._meta_feed_task = meta_task
        session._bbo_poll_task = bbo_task
        ingest = MagicMock()
        ingest.stop = AsyncMock()
        session._trades_ingest = ingest
        await session.stop()
        assert session._running is False
        assert session._bbo_poll_task is None
        assert session._meta_feed_task is not None  # cancelled, not held as None
        assert session._trades_ingest is None
        session._execution.stop.assert_awaited_once()


class TestFacade:
    def test_snapshot_state(self) -> None:
        """L1821-1851: structured live-state snapshot."""
        session = TradingSession(AppConfig(), [])
        session._portfolio.update_position("BTC/USDT", 1.0, 100.0)
        session._execution.order_manager.get_open_orders = MagicMock(return_value=[])
        snap = session.snapshot_state()
        assert snap["health"]["running"] is False
        assert snap["cash"] == pytest.approx(100000.0 - 100.0)
        assert snap["portfolio"]["positions"] == 1
        assert len(snap["positions"]) == 1
        assert snap["kill_switch"] is None

    @pytest.mark.asyncio
    async def test_activate_kill_switch_raises_when_none(self) -> None:
        """L1863: no kill switch → RuntimeError."""
        session = TradingSession(AppConfig(), [])
        with pytest.raises(RuntimeError, match="kill switch"):
            await session.activate_kill_switch("test")

    @pytest.mark.asyncio
    async def test_activate_kill_switch_success(self) -> None:
        """L1864-1869: kill switch activate + release all."""
        session = TradingSession(AppConfig(), [])
        kill = MagicMock()
        kill.activate = AsyncMock(return_value={"activated": True})
        session._kill_switch = kill
        session._portfolio.reserve("r1", "BTC/USDT", 1000.0, "probe")
        res = await session.activate_kill_switch("test")
        assert res == {"activated": True}
        assert session._portfolio.total_pending_exposure == 0.0

    def test_adjust_capital(self) -> None:
        """L1871-1874: capital adjustment updates cash + baseline."""
        session = TradingSession(AppConfig(), [])
        session.adjust_capital(150000.0)
        assert session._portfolio.cash == pytest.approx(150000.0)
        session.adjust_capital(150000.0)  # no delta → baseline only
        assert session._portfolio.cash == pytest.approx(150000.0)