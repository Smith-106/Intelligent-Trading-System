"""Coverage completion (round 3) for quantflow/strategy/engine.py.

Drives the remaining uncovered lines/branches:
- L1193-1195: trades-ingest ``_ensure_connect`` background task body.
- L1234-1239 + L1263-1265: BBO poll own-fetcher connect-failure + disconnect.
- L1245-1251 + L1256: BBO poll ticker failure / missing-quote branches.
- L1300-1308: meta feed skip-window branches + cycle-error branch.
- L1315-1353 / L1415-1442: real ``_meta_poll_funding`` / ``_meta_poll_oi`` bodies.
- L1402: funding-risk-gate kill-switch already active.
- L388: checkpoint restore with no snapshot and no store error.
- L987: zero cash-delta restore.
- L569 / L646: on_bar close<=0 and zero base-equity branches.
- L728: consolidation returning None.
- L937: reduce-only close order not FILLED.
- L1535/L1544/L1693/L1697/L1701: paper local-replay fallback branches.

All external components (fetchers, sinks, stores, gateways) are mocked per the
project unit-test convention.
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
from quantflow.strategy.engine import TradingSession


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


def _snap(rate: float = 0.0005, oi: float = 1000.0) -> SimpleNamespace:
    return SimpleNamespace(
        fetched_at_ms=1700000000000,
        settlement_interval_ms=3600000,
        funding_rate=rate,
        open_interest=oi,
    )


class TestTradesIngestEnsureConnect:
    @pytest.mark.asyncio
    async def test_ensure_connect_task_runs_and_suppresses(self) -> None:
        """L1193-1195: real create_task executes the connect closure; raise suppressed."""
        session = TradingSession(AppConfig(), [])
        session._symbols = ["BTC/USDT"]
        session._trades_fetcher = None
        fake_fetcher = MagicMock()
        fake_fetcher.fetch_trades = AsyncMock()
        fake_fetcher.connect = AsyncMock(side_effect=Exception("connect boom"))
        fake_loop = MagicMock()
        with (
            patch("quantflow.data.trades_ingest.TradesIngestLoop", return_value=fake_loop),
            patch("quantflow.data.trades_store.TradesStore", return_value=MagicMock()),
            patch("quantflow.data.fetcher.DataFetcher", return_value=fake_fetcher),
            patch("asyncio.create_task", side_effect=lambda c: asyncio.ensure_future(c)),
        ):
            session._start_trades_ingest()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        fake_fetcher.connect.assert_awaited_once()
        fake_loop.start.assert_called_once()
        assert session._trades_fetcher is fake_fetcher


class TestBboPollLoopBranches:
    @pytest.mark.asyncio
    async def test_own_fetcher_connect_failure_and_disconnect(self) -> None:
        """L1234-1239 + L1263-1265: own DataFetcher, connect fails, finally disconnects."""
        cfg = AppConfig()
        cfg.execution.bbo_poll_interval_s = 1.0
        session = TradingSession(cfg, [])
        session._symbols = ["BTC/USDT"]
        session._running = True
        fake = MagicMock()
        fake.connect = AsyncMock(side_effect=Exception("bbo connect fail"))
        fake.fetch_ticker = AsyncMock(return_value={"bid": 1.0, "ask": 2.0})
        fake.disconnect = AsyncMock()
        with (
            patch("quantflow.data.fetcher.DataFetcher", return_value=fake),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):

            async def _stop(*a, **k):
                session._running = False

            mock_sleep.side_effect = _stop
            await session._bbo_poll_loop()
        fake.connect.assert_awaited_once()
        fake.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ticker_failure_and_missing_quote(self) -> None:
        """L1245-1251 (fetch raise) + L1256 (bid/ask missing) → tolerated continue."""
        cfg = AppConfig()
        cfg.execution.bbo_poll_interval_s = 1.0
        session = TradingSession(cfg, [])
        session._symbols = ["BTC/USDT", "ETH/USDT"]
        session._running = True
        fake = MagicMock()
        fake.fetch_ticker = AsyncMock(
            side_effect=[Exception("ticker down"), {"bid": None, "ask": None}]
        )
        session._bbo_fetcher = fake
        session.push_ticker_bbo = MagicMock()
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

            async def _stop(*a, **k):
                session._running = False

            mock_sleep.side_effect = _stop
            await session._bbo_poll_loop()
        assert fake.fetch_ticker.await_count == 2
        session.push_ticker_bbo.assert_not_called()


class TestMetaFeedLoopBranches:
    @pytest.mark.asyncio
    async def test_two_cycles_skip_poll_windows(self) -> None:
        """L1300-1303 + L1303-1308: funding/OI deadlines not yet due → skipped."""
        session = TradingSession(AppConfig(), [])
        session._symbols = ["BTC/USDT"]
        session._meta_fetcher = MagicMock()
        session._meta_fetcher.connect = AsyncMock()
        session._dq_monitor = MagicMock()
        session._running = True
        with (
            patch.object(session, "_meta_poll_funding", new_callable=AsyncMock) as mock_f,
            patch.object(session, "_meta_poll_oi", new_callable=AsyncMock) as mock_oi,
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            sleeps = 0

            async def _stop(*a, **k):
                nonlocal sleeps
                sleeps += 1
                if sleeps >= 2:
                    session._running = False

            mock_sleep.side_effect = _stop
            await session._meta_feed_loop()
        assert mock_f.await_count == 1
        assert mock_oi.await_count == 1

    @pytest.mark.asyncio
    async def test_cycle_error_is_logged_not_fatal(self) -> None:
        """L1306-1307: a failing poll cycle is caught and the loop keeps going."""
        session = TradingSession(AppConfig(), [])
        session._symbols = ["BTC/USDT"]
        session._meta_fetcher = MagicMock()
        session._meta_fetcher.connect = AsyncMock()
        session._dq_monitor = MagicMock()
        session._running = True
        with (
            patch.object(
                session, "_meta_poll_funding", new_callable=AsyncMock, side_effect=Exception("boom")
            ),
            patch.object(session, "_meta_poll_oi", new_callable=AsyncMock),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):

            async def _stop(*a, **k):
                session._running = False

            mock_sleep.side_effect = _stop
            await session._meta_feed_loop()
        assert session._running is False


class TestMetaPollBodies:
    @pytest.mark.asyncio
    async def test_meta_poll_funding_fetcher_none_returns(self) -> None:
        """L1315-1318: missing fetcher/dq → early return."""
        session = TradingSession(AppConfig(), [])
        assert await session._meta_poll_funding(["BTC/USDT"]) is None

    @pytest.mark.asyncio
    async def test_meta_poll_funding_success_and_failure_paths(self) -> None:
        """L1319-1362: per-symbol isolation — fetch raise, stale dq, clean path."""
        session = TradingSession(AppConfig(), [])
        fake_fetcher = MagicMock()
        snap = _snap()
        fake_fetcher.fetch_funding_rate = AsyncMock(
            side_effect=[Exception("fetch fail"), snap, snap]
        )
        fake_dq = MagicMock()
        dq_invalid = SimpleNamespace(valid=False, violations=["stale"])
        dq_valid = SimpleNamespace(valid=True, violations=[])
        fake_dq.validate_funding_rate = MagicMock(side_effect=[dq_invalid, dq_valid])
        session._meta_fetcher = fake_fetcher
        session._dq_monitor = fake_dq
        session._sink.send_alert = AsyncMock()
        session._event_bus.publish = MagicMock()
        session._last_funding_rate = {}
        inst = MagicMock()
        session._instances = {("funding_rate", "BTC/USDT"): inst}
        session._risk_pauses.clear()

        await session._meta_poll_funding(["A", "BTC/USDT", "ETH/USDT"])

        # A: fetch raised → skipped; BTC/USDT: stale dq alert + instance update;
        # ETH/USDT: clean path with no updateable instance (plain object).
        session._sink.send_alert.assert_awaited_once()
        inst.update_funding_rate.assert_called_once_with(snap.funding_rate)
        assert session._last_funding_rate["BTC/USDT"] == snap.funding_rate
        assert session._last_funding_rate["ETH/USDT"] == snap.funding_rate
        assert session._meta_fresh["BTC/USDT"]["funding"] is True
        published = [c.args[0] for c in session._event_bus.publish.call_args_list]
        assert len(published) == 2  # BTC + ETH, A was skipped
        assert all(p.type == "funding" for p in published)

    @pytest.mark.asyncio
    async def test_meta_poll_oi_success_and_failure_paths(self) -> None:
        """L1415-1445: per-symbol isolation — fetch raise, stale dq, clean path."""
        session = TradingSession(AppConfig(), [])
        fake_fetcher = MagicMock()
        snap = _snap()
        fake_fetcher.fetch_open_interest = AsyncMock(side_effect=[Exception("oi down"), snap, snap])
        fake_dq = MagicMock()
        fake_dq.validate_open_interest = MagicMock(
            side_effect=[
                SimpleNamespace(valid=False, violations=["stale"]),
                SimpleNamespace(valid=True, violations=[]),
            ]
        )
        session._meta_fetcher = fake_fetcher
        session._dq_monitor = fake_dq
        session._sink.send_alert = AsyncMock()
        session._event_bus.publish = MagicMock()
        inst = MagicMock()
        session._instances = {("funding_rate", "BTC/USDT"): inst}

        await session._meta_poll_oi(["A", "BTC/USDT", "ETH/USDT"])

        session._sink.send_alert.assert_awaited_once()
        inst.update_open_interest.assert_called_once_with(snap.open_interest)
        assert session._meta_fresh["BTC/USDT"]["oi"] is True
        assert session._meta_fresh["ETH/USDT"]["oi"] is True
        published = [c.args[0] for c in session._event_bus.publish.call_args_list]
        assert len(published) == 2
        assert all(p.type == "open_interest" for p in published)

    @pytest.mark.asyncio
    async def test_meta_poll_oi_fetcher_none_returns(self) -> None:
        """L1415-1418: missing fetcher/dq → early return."""
        session = TradingSession(AppConfig(), [])
        assert await session._meta_poll_oi(["BTC/USDT"]) is None


class TestFundingRiskGateActiveKill:
    @pytest.mark.asyncio
    async def test_kill_switch_already_active_skips_task(self) -> None:
        """L1402: kill switch already active → no fire-and-forget task."""
        cfg = AppConfig()
        cfg.risk.funding_risk_gate_enabled = True
        cfg.risk.funding_risk_gate_kill = True
        cfg.risk.max_funding_rate_abs = 0.001
        session = TradingSession(cfg, [])
        kill = MagicMock()
        kill.is_active = True
        session._kill_switch = kill
        session._event_bus.publish = MagicMock()
        with patch("asyncio.create_task") as mock_task:
            session.note_funding_rate("BTC/USDT", 0.005)
            mock_task.assert_not_called()
        assert "funding_risk_gate" in session._risk_pauses.reasons


class TestStartCheckpointNoError:
    @pytest.mark.asyncio
    async def test_no_snapshot_and_no_store_error_keeps_verified(self) -> None:
        """L388: load_checkpoint None + no last_error → elif skipped, verified stays True."""
        cfg = AppConfig()
        cfg.state.enabled = True
        session = TradingSession(cfg, [])
        fake_store = MagicMock()
        fake_store.load_checkpoint.return_value = None
        fake_store.last_error = None
        with (
            patch("quantflow.strategy.engine.StateStore", return_value=fake_store),
            patch.object(session._execution, "start", new_callable=AsyncMock),
        ):
            await session.start(mode="paper")
        assert session._recovery_verified is True


class TestRestoreSnapshotZeroDelta:
    def test_zero_cash_delta_skips_update(self) -> None:
        """L987: cash delta ~0 → update_cash not called."""
        session = TradingSession(AppConfig(), [])
        session._portfolio.update_cash = MagicMock()
        snapshot = SessionSnapshot(
            saved_at_ms=1,
            mode="paper",
            cash=session._portfolio.cash,  # same cash → zero delta
            positions=[],
            open_orders=[],
            equity=100000.0,
        )
        session._restore_from_snapshot(snapshot)
        session._portfolio.update_cash.assert_not_called()


class TestOnBarExtraBranches:
    def _session(self, cfg: AppConfig) -> TradingSession:
        session = TradingSession(cfg, [])
        session._running = True
        session._sink = MagicMock()
        return session

    @pytest.mark.asyncio
    async def test_close_zero_skips_symbol_close_and_bar_proxy(self) -> None:
        """L569 + L495: close<=0 skips _symbol_close_prev; invalid low skips orderbook."""
        cfg = AppConfig()
        cfg.risk.portfolio_optimization.enabled = True
        cfg.risk.portfolio_optimization.level = "symbol"
        cfg.risk.portfolio_optimization.rebalance_every_n_bars = 1
        session = self._session(cfg)
        session._portfolio_optimizer.compute = MagicMock(return_value={"BTC/USDT": 1.0})
        session._symbol_close_prev["BTC/USDT"] = 100.0
        session._execution.update_orderbook = MagicMock()
        with (
            patch.object(session, "_update_portfolio_observability"),
            patch.object(session, "_record_bar_latency"),
        ):
            await session.on_bar(_make_bar(price=0.0, idx=0))
        # close<=0: _symbol_close_prev must NOT be overwritten with 0.0
        assert session._symbol_close_prev["BTC/USDT"] == 100.0
        # low=-1.0 invalid → no bar-proxy orderbook push
        session._execution.update_orderbook.assert_not_called()

    @pytest.mark.asyncio
    async def test_zero_base_equity_skips_weekly_pnl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L646: base_equity <= 0 → weekly pnl not pushed."""
        session = self._session(AppConfig())
        session._risk_engine.set_weekly_pnl = MagicMock()
        monkeypatch.setattr(
            "quantflow.strategy.engine._weekly_base_equity", lambda *a, **k: (0.0, 0, 0)
        )
        with (
            patch.object(session, "_update_portfolio_observability"),
            patch.object(session, "_record_bar_latency"),
        ):
            await session.on_bar(_make_bar())
        session._risk_engine.set_weekly_pnl.assert_not_called()

    @pytest.mark.asyncio
    async def test_consolidation_none_leaves_no_signal(self) -> None:
        """L728: >1 signals per symbol but consolidation returns None → no signal."""
        session = self._session(AppConfig())
        session._symbols = ["BTC/USDT"]
        strat = MagicMock()
        strat.name = "s1"
        strat.required_regime = "any"
        session._strategies = [strat]
        session._instances = {("s1", "BTC/USDT"): MagicMock()}
        ctx = MagicMock()
        ctx.flush_signals.return_value = [_signal(), _signal()]
        session._contexts = {("s1", "BTC/USDT"): ctx}
        session._signal_gen.consolidate_signals = MagicMock(return_value=None)
        with (
            patch.object(session, "_update_portfolio_observability"),
            patch.object(session, "_record_bar_latency"),
            patch.object(session, "_process_signal", new_callable=AsyncMock) as mock_process,
        ):
            await session.on_bar(_make_bar())
        mock_process.assert_not_awaited()


class TestClosePositionNotFilled:
    @pytest.mark.asyncio
    async def test_close_order_not_filled_skips_observability(self) -> None:
        """L937: reduce-only close returning non-FILLED → no observability refresh."""
        session = TradingSession(AppConfig(), [])
        session._risk_engine.check = MagicMock(return_value=RiskDecision(passed=True))
        session._position_sizer.size = MagicMock(return_value=1500.0)
        session._portfolio.update_position("BTC/USDT", 1.0, 100.0)
        session._execution.submit_order = AsyncMock(
            return_value=Order(
                order_id="o1",
                symbol="BTC/USDT",
                side=OrderSide.SELL,
                order_type="market",
                quantity=1.0,
                status=OrderStatus.SUBMITTED,
            )
        )
        session._event_bus.publish = MagicMock()
        session._record_signal_latency = MagicMock()
        session._update_portfolio_observability = MagicMock()
        await session._process_signal_inner(_signal(direction=Direction.FLAT))
        session._update_portfolio_observability.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_order_filled_refreshes_observability(self) -> None:
        """L937-941: FILLED close → observability refresh."""
        session = TradingSession(AppConfig(), [])
        session._risk_engine.check = MagicMock(return_value=RiskDecision(passed=True))
        session._position_sizer.size = MagicMock(return_value=1500.0)
        session._portfolio.update_position("BTC/USDT", 1.0, 100.0)
        session._execution.submit_order = AsyncMock(
            return_value=Order(
                order_id="o1",
                symbol="BTC/USDT",
                side=OrderSide.SELL,
                order_type="market",
                quantity=1.0,
                status=OrderStatus.FILLED,
            )
        )
        session._event_bus.publish = MagicMock()
        session._record_signal_latency = MagicMock()
        session._update_portfolio_observability = MagicMock()
        await session._process_signal_inner(_signal(direction=Direction.FLAT))
        session._update_portfolio_observability.assert_called_once()


def _ohlcv_frame(n: int = 5, start_ts: int = 1700000000000) -> pd.DataFrame:
    ts = [start_ts + i * 60000 for i in range(n)]
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.5] * n,
            "volume": [1000.0] * n,
        }
    )


class TestRunDataLoopPaperFallback:
    @pytest.mark.asyncio
    async def test_timeframe_fallback_and_empty_inloop_query(self) -> None:
        """L1535/L1544-1555/L1693-1695/L1697-1718: fallback to alternate data + skip."""
        cfg = AppConfig()  # default mode=paper
        session = TradingSession(cfg, [])
        fake_store = MagicMock()
        fake_store.query.side_effect = [
            pd.DataFrame(),  # timeframe query → empty
            _ohlcv_frame(3),  # fallback → non-empty (warning path)
            pd.DataFrame(),  # in-loop query → empty (skip path)
        ]
        fake_store.close = MagicMock()
        fake_fetcher = MagicMock()
        fake_fetcher.connect = AsyncMock()
        fake_fetcher.fetch_ohlcv = AsyncMock(return_value=pd.DataFrame())
        fake_fetcher.disconnect = AsyncMock()
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.data.fetcher.DataFetcher", return_value=fake_fetcher),
            patch.object(session, "on_bar", new_callable=AsyncMock),
            patch.object(session, "check_health"),
            patch.object(session, "_periodic_maintenance", new_callable=AsyncMock),
            patch.object(session._execution, "check_timeouts", return_value=[]),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            sleeps = 0

            async def _stop(*a, **k):
                nonlocal sleeps
                sleeps += 1
                if sleeps >= 2:
                    session._running = False

            mock_sleep.side_effect = _stop
            session._running = True
            await session.run_data_loop("BTC/USDT", "1h", 1)
        assert sleeps == 2
        fake_store.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stale_timestamps_skipped_in_local_loop(self) -> None:
        """L1701: duplicate/older timestamps do not re-fire on_bar."""
        cfg = AppConfig()
        session = TradingSession(cfg, [])
        fake_store = MagicMock()
        stale = _ohlcv_frame(2, start_ts=1700000000000)
        fake_store.query.side_effect = [
            _ohlcv_frame(3),  # initial load
            stale,  # in-loop query → same timestamps as already seen
        ]
        fake_store.close = MagicMock()
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch.object(session, "on_bar", new_callable=AsyncMock) as mock_on_bar,
            patch.object(session, "check_health"),
            patch.object(session, "_periodic_maintenance", new_callable=AsyncMock),
            patch.object(session._execution, "check_timeouts", return_value=[]),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            sleeps = 0

            async def _stop(*a, **k):
                nonlocal sleeps
                sleeps += 1
                if sleeps >= 2:
                    session._running = False

            mock_sleep.side_effect = _stop
            session._running = True
            await session.run_data_loop("BTC/USDT", "1h", 1)
        # Only the 3 initial rows fire on_bar; the 2 stale rows are skipped.
        assert mock_on_bar.await_count == 3
