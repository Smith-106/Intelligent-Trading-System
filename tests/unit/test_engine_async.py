"""Tests for strategy/engine.py — async start(), run_data_loop(), on_bar() uncovered paths."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from quantflow.common.config import AppConfig
from quantflow.common.models import Bar
from quantflow.indicators.regime import MarketRegimeDetector
from quantflow.strategy.engine import TradingSession


class TestEnsureMetricsServerStarted:
    """start_metrics_server is idempotent per port (ISS-019 moved the dedup
    out of engine._ensure_metrics_server_started into metrics.py)."""

    def test_first_call_starts_server(self):
        from quantflow.monitoring import metrics

        port = 9091
        # Isolate state for this port so the test is order-independent.
        metrics._METRICS_SERVER_STATE.pop(port, None)
        with patch("quantflow.monitoring.metrics.start_http_server") as mock_start:
            metrics.start_metrics_server(port)
            mock_start.assert_called_once_with(port)

    def test_second_call_skips(self):
        from quantflow.monitoring import metrics

        port = 9092
        metrics._METRICS_SERVER_STATE.pop(port, None)
        with patch("quantflow.monitoring.metrics.start_http_server") as mock_start:
            metrics.start_metrics_server(port)
            metrics.start_metrics_server(port)  # second call is a no-op
            mock_start.assert_called_once_with(port)


class TestTradingSessionStartWinRate:
    @pytest.mark.asyncio
    async def test_start_with_win_rates(self):
        """Lines 104-117: start() with strategy_win_rates sets allocation."""
        from quantflow.strategy.base import StrategyBase

        class DummyStrategy(StrategyBase):
            def on_init(self, ctx):
                pass

            def on_bar(self, ctx, bar):
                pass

            def generate_signals(self, df):
                return pd.Series(dtype=bool), pd.Series(dtype=bool)

        config = AppConfig()
        s1 = DummyStrategy(name="s1")
        s2 = DummyStrategy(name="s2")
        session = TradingSession(
            config,
            [s1, s2],
            strategy_win_rates={"s1": 0.8, "s2": 0.4},
        )

        with (
            patch.object(session._execution, "start", new_callable=AsyncMock),
            patch("quantflow.strategy.engine._ensure_metrics_server_started"),
        ):
            await session.start(mode="paper")

        # Verify allocation was set
        alloc = session._portfolio.allocation
        assert "s1" in alloc
        assert "s2" in alloc
        assert alloc["s1"] > alloc["s2"]  # higher win rate → more allocation
        assert sum(alloc.values()) == pytest.approx(1.0)
        session._running = False

    @pytest.mark.asyncio
    async def test_start_with_zero_win_rates(self):
        """Lines 113-114: total_wr == 0 → equal allocation."""
        from quantflow.strategy.base import StrategyBase

        class DummyStrategy(StrategyBase):
            def on_init(self, ctx):
                pass

            def on_bar(self, ctx, bar):
                pass

            def generate_signals(self, df):
                return pd.Series(dtype=bool), pd.Series(dtype=bool)

        config = AppConfig()
        s1 = DummyStrategy(name="s1")
        s2 = DummyStrategy(name="s2")
        session = TradingSession(
            config,
            [s1, s2],
            strategy_win_rates={"s1": 0.0, "s2": 0.0},
        )

        with (
            patch.object(session._execution, "start", new_callable=AsyncMock),
            patch("quantflow.strategy.engine._ensure_metrics_server_started"),
        ):
            await session.start(mode="paper")

        alloc = session._portfolio.allocation
        assert alloc["s1"] == pytest.approx(0.5)
        assert alloc["s2"] == pytest.approx(0.5)
        session._running = False


class TestTradingSessionOnBarRegimeGating:
    @pytest.mark.asyncio
    async def test_on_bar_trending_gates_mean_reversion(self):
        """Lines 178-181: regime gating in on_bar()."""
        from quantflow.strategy.base import StrategyBase

        class TrendStrategy(StrategyBase):
            required_regime = "trending"

            def on_init(self, ctx):
                pass

            def on_bar(self, ctx, bar):
                from quantflow.common.models import Direction

                ctx.emit_signal(
                    "BTC/USDT", Direction.LONG, strength=0.5, price=bar.close, strategy_id=self.name
                )

            def generate_signals(self, df):
                return pd.Series(dtype=bool), pd.Series(dtype=bool)

        class MRStrategy(StrategyBase):
            required_regime = "mean_reversion"

            def on_init(self, ctx):
                pass

            def on_bar(self, ctx, bar):
                from quantflow.common.models import Direction

                ctx.emit_signal(
                    "BTC/USDT",
                    Direction.SHORT,
                    strength=0.3,
                    price=bar.close,
                    strategy_id=self.name,
                )

            def generate_signals(self, df):
                return pd.Series(dtype=bool), pd.Series(dtype=bool)

        config = AppConfig()
        t = TrendStrategy(name="trend_s")
        t.required_regime = "trending"
        m = MRStrategy(name="mr_s")
        m.required_regime = "mean_reversion"
        session = TradingSession(config, [t, m])

        with (
            patch.object(session._execution, "start", new_callable=AsyncMock),
            patch("quantflow.strategy.engine._ensure_metrics_server_started"),
            patch.object(MarketRegimeDetector, "update") as mock_regime,
            patch.object(session._execution, "update_market_price"),
            patch.object(session._signal_gen, "consolidate_signals", return_value=None),
            patch.object(session._execution, "submit_order", new_callable=AsyncMock),
            patch.object(session, "_update_portfolio_observability"),
            patch.object(session, "_record_bar_latency"),
        ):
            mock_regime.return_value = MagicMock(is_trending=True)
            await session.start(mode="paper")
            bar = Bar("BTC/USDT", 1700000000, 100.0, 101.0, 99.0, 100.5, 1000.0)
            await session.on_bar(bar)

        # trending strategy should have been called, mean_reversion should not
        # Check contexts
        assert ("trend_s", "") in session._contexts
        assert ("mr_s", "") in session._contexts
        session._running = False


class TestTradingSessionPositionSizingClamp:
    """Regression guard for the max_position_pct units fix (commit eebbc25).

    Before the fix, TradingSession passed ``position_limit_pct * 100`` (=2000%)
    to PositionSizer, making the max-position clamp a no-op and silently
    ignoring the risk config. This test locks in the wired clamp so the *100
    bug cannot silently return: even a high-win-rate strategy whose raw Kelly
    size would exceed ``position_limit_pct`` must be capped.
    """

    @pytest.mark.asyncio
    async def test_high_win_rate_order_clamped_to_position_limit(self):
        from quantflow.strategy.base import StrategyBase

        class AggressiveStrategy(StrategyBase):
            required_regime = ""

            def on_init(self, ctx):
                pass

            def on_bar(self, ctx, bar):
                from quantflow.common.models import Direction

                ctx.emit_signal(
                    "BTC/USDT",
                    Direction.LONG,
                    strength=1.0,
                    price=bar.close,
                    strategy_id=self.name,
                )

            def generate_signals(self, df):
                return pd.Series(dtype=bool), pd.Series(dtype=bool)

        config = AppConfig()
        # position_limit_pct defaults to 0.20 (20%). Use a high per-strategy
        # win rate so raw Kelly sizing (0.5 * kelly * raw_kelly * strength)
        # would exceed 20% without the clamp.
        session = TradingSession(
            config,
            [AggressiveStrategy(name="agg_s")],
            strategy_win_rates={"agg_s": 0.70},
        )

        submitted = []
        with (
            patch.object(session._execution, "start", new_callable=AsyncMock),
            patch("quantflow.strategy.engine._ensure_metrics_server_started"),
            patch.object(MarketRegimeDetector, "update") as mock_regime,
            patch.object(session._execution, "update_market_price"),
            patch.object(session._execution, "submit_order", new_callable=AsyncMock) as mock_submit,
            patch.object(session, "_update_portfolio_observability"),
            patch.object(session, "_record_bar_latency"),
            patch.object(session, "_record_signal_latency"),
        ):
            mock_regime.return_value = MagicMock(is_trending=True)
            await session.start(mode="paper")
            bar = Bar("BTC/USDT", 1700000000, 100.0, 101.0, 99.0, 100.0, 1000.0)
            await session.on_bar(bar)
            submitted = list(mock_submit.call_args_list)

        # An order should have been submitted (raw Kelly at wr=0.7 > 0 so size>0).
        assert len(submitted) == 1
        order_request = submitted[0].args[0]
        # order notional = quantity * price; price was 100.0
        notional = abs(order_request.quantity) * 100.0
        # total_value ~ initial_capital 100000 (no positions yet).
        # Clamp must keep notional <= position_limit_pct (0.20) * total_value,
        # i.e. <= 20000. Without the clamp it would be ~27445 (27.45%).
        assert notional <= 100000 * config.risk.position_limit_pct + 1.0
        # And it should be a non-trivial order (the clamp engaged, not zeroed).
        assert notional > 0
        session._running = False


class TestTradingSessionRunDataLoop:
    @pytest.mark.asyncio
    async def test_run_data_loop_paper_with_local_data(self):
        """Lines 328-353: run_data_loop in paper mode with local data."""
        config = AppConfig()
        session = TradingSession(config, [])

        mock_store = MagicMock()
        dates = pd.date_range("2024-01-01", periods=5, freq="h")
        mock_store.query.return_value = pd.DataFrame(
            {
                "timestamp": [int(ts.timestamp() * 1000) for ts in dates],
                "open": [100.0] * 5,
                "high": [101.0] * 5,
                "low": [99.0] * 5,
                "close": [100.5] * 5,
                "volume": [1000.0] * 5,
            }
        )
        mock_store.close = MagicMock()

        call_count = 0

        async def mock_on_bar(bar):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                session._running = False

        with (
            patch("quantflow.data.store.DataStore", return_value=mock_store),
            patch.object(session, "on_bar", side_effect=mock_on_bar),
            patch.object(session, "check_health"),
            patch.object(session._execution, "check_timeouts"),
            patch.object(session._execution, "start", new_callable=AsyncMock),
            patch("quantflow.strategy.engine._ensure_metrics_server_started"),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await session.start(mode="paper")
            session._running = True
            await session.run_data_loop("BTC/USDT", "1h", 1)

        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_run_data_loop_local_exception(self):
        """Lines 469-471: _run_local_data_loop exception path inside the loop."""
        config = AppConfig()
        session = TradingSession(config, [])

        mock_store = MagicMock()
        # First query succeeds (returns data for paper loop entry)
        dates = pd.date_range("2024-01-01", periods=3, freq="h")
        first_frame = pd.DataFrame(
            {
                "timestamp": [int(ts.timestamp() * 1000) for ts in dates],
                "open": [100.0] * 3,
                "high": [101.0] * 3,
                "low": [99.0] * 3,
                "close": [100.5] * 3,
                "volume": [1000.0] * 3,
            }
        )
        # Second query (inside loop) raises exception
        mock_store.query.side_effect = [first_frame, Exception("data error")]
        mock_store.close = MagicMock()

        async def mock_on_bar(bar):
            pass

        with (
            patch("quantflow.data.store.DataStore", return_value=mock_store),
            patch.object(session, "on_bar", side_effect=mock_on_bar),
            patch.object(session, "check_health"),
            patch.object(session._execution, "check_timeouts"),
            patch.object(session._execution, "start", new_callable=AsyncMock),
            patch("quantflow.strategy.engine._ensure_metrics_server_started"),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            # Stop after 2 iterations
            sleep_count = 0

            async def stop_after_sleep(*args, **kwargs):
                nonlocal sleep_count
                sleep_count += 1
                if sleep_count >= 2:
                    session._running = False

            mock_sleep.side_effect = stop_after_sleep

            await session.start(mode="paper")
            session._running = True
            await session.run_data_loop("BTC/USDT", "1h", 1)

        # The exception was caught and recorded as last_error
        assert session._last_error is not None
        assert "data error" in session._last_error

    @pytest.mark.asyncio
    async def test_run_data_loop_live_fetch_error(self):
        """Lines 366-373: run_data_loop live mode fetch error."""
        config = AppConfig()
        config.execution.mode = "live"
        session = TradingSession(config, [])

        mock_fetcher = MagicMock()
        mock_fetcher.connect = AsyncMock(side_effect=Exception("Connection failed"))
        mock_fetcher.disconnect = AsyncMock()

        with (
            patch("quantflow.data.fetcher.DataFetcher", return_value=mock_fetcher),
            patch("quantflow.data.store.DataStore"),
            patch.object(session, "check_health"),
            patch.object(session._execution, "check_timeouts"),
            patch.object(session._execution, "start", new_callable=AsyncMock),
            patch("quantflow.strategy.engine._ensure_metrics_server_started"),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            # Stop after 2 sleep iterations
            sleep_count = 0

            async def stop_after_sleep(*args, **kwargs):
                nonlocal sleep_count
                sleep_count += 1
                if sleep_count >= 2:
                    session._running = False

            mock_sleep.side_effect = stop_after_sleep

            await session.start(
                mode="live",
                gateway_config={
                    "api_key": "test",
                    "secret": "test",
                    "passphrase": "test",
                    "sandbox": False,
                },
            )
            session._running = True
            await session.run_data_loop("BTC/USDT", "1h", 1)

        assert session._last_error is not None


class TestTradingSessionStop:
    @pytest.mark.asyncio
    async def test_stop(self):
        """Lines 498-502: stop() sets _running = False."""
        config = AppConfig()
        session = TradingSession(config, [])
        session._running = True
        with patch.object(session._execution, "stop", new_callable=AsyncMock):
            await session.stop()
        assert session._running is False


class TestTradingSessionOnRiskEvent:
    def test_on_risk_event_emergency(self):
        """Line 312-313: Emergency risk event."""
        config = AppConfig()
        config.risk.kill_switch_enabled = True
        session = TradingSession(config, [])
        mock_kill = MagicMock()
        mock_kill.is_active = False
        # DEF-REV011-B: activate() is awaited in a fire-and-forget task —
        # must be an AsyncMock so create_task gets a coroutine.
        mock_kill.activate = AsyncMock(return_value={"status": "activated"})
        session._kill_switch = mock_kill

        from quantflow.common.event_bus import Event

        event = Event(type="risk", data={"severity": "emergency"})

        # DEF-REV011-B: emergency now arms the kill switch via a fire-and-
        # forget task; run inside a loop so create_task works, then drain.
        import asyncio as _aio

        async def _drive():
            session._on_risk_event(event)
            pending = [t for t in session._background_tasks if not t.done()]
            if pending:
                await _aio.gather(*pending, return_exceptions=True)

        _aio.run(_drive())
        mock_kill.activate.assert_called_once()

    def test_on_risk_event_non_emergency(self):
        config = AppConfig()
        session = TradingSession(config, [])
        mock_kill = MagicMock()
        mock_kill.is_active = False
        session._kill_switch = mock_kill

        from quantflow.common.event_bus import Event

        event = Event(type="risk", data={"severity": "warn"})
        session._on_risk_event(event)


class TestTradingSessionLiveKillSwitchEnforcement:
    """Safety: live mode MUST run with kill switch armed (CLAUDE.md).

    start() refuses to enter live trading when kill_switch_enabled=False,
    rather than silently trading live without an emergency-stop path.
    """

    @pytest.mark.asyncio
    async def test_live_refuses_without_kill_switch(self):
        """mode='live' + kill_switch_enabled=False → RuntimeError, not started."""
        from quantflow.strategy.base import StrategyBase

        class DummyStrategy(StrategyBase):
            def on_init(self, ctx):
                pass

            def on_bar(self, ctx, bar):
                pass

            def generate_signals(self, df):
                return pd.Series(dtype=bool), pd.Series(dtype=bool)

        config = AppConfig()
        config.risk.kill_switch_enabled = False
        session = TradingSession(config, [DummyStrategy(name="s1")])

        with (
            patch.object(session._execution, "start", new_callable=AsyncMock),
            patch("quantflow.strategy.engine._ensure_metrics_server_started"),
        ):
            with pytest.raises(RuntimeError, match="Kill switch must be enabled"):
                await session.start(mode="live")

        assert session._running is False
        assert session._kill_switch is None

    @pytest.mark.asyncio
    async def test_live_allows_with_kill_switch(self):
        """mode='live' + kill_switch_enabled=True + gateway → kill switch armed."""
        from quantflow.strategy.base import StrategyBase

        class DummyStrategy(StrategyBase):
            def on_init(self, ctx):
                pass

            def on_bar(self, ctx, bar):
                pass

            def generate_signals(self, df):
                return pd.Series(dtype=bool), pd.Series(dtype=bool)

        config = AppConfig()
        config.risk.kill_switch_enabled = True
        session = TradingSession(config, [DummyStrategy(name="s1")])

        # live mode requires a gateway present on the execution engine
        session._execution._gateway = MagicMock()

        with (
            patch.object(session._execution, "start", new_callable=AsyncMock),
            patch("quantflow.strategy.engine._ensure_metrics_server_started"),
        ):
            await session.start(mode="live")

        assert session._running is True
        assert session._kill_switch is not None
        session._running = False

    @pytest.mark.asyncio
    async def test_paper_allows_without_kill_switch(self):
        """mode='paper' is never force-gated — kill switch optional in paper."""
        from quantflow.strategy.base import StrategyBase

        class DummyStrategy(StrategyBase):
            def on_init(self, ctx):
                pass

            def on_bar(self, ctx, bar):
                pass

            def generate_signals(self, df):
                return pd.Series(dtype=bool), pd.Series(dtype=bool)

        config = AppConfig()
        config.risk.kill_switch_enabled = False
        session = TradingSession(config, [DummyStrategy(name="s1")])

        with (
            patch.object(session._execution, "start", new_callable=AsyncMock),
            patch("quantflow.strategy.engine._ensure_metrics_server_started"),
        ):
            await session.start(mode="paper")

        assert session._running is True
        assert session._kill_switch is None
        session._running = False
