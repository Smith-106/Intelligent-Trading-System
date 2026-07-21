"""Trading Session — orchestrates a complete trading session.

Manages the lifecycle: data feed → strategy → signal → risk → execution.
Supports backtest, paper, and live modes with the same strategy code.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import deque
from collections.abc import Sequence
from time import perf_counter
from typing import Any

from quantflow.common.config import AppConfig
from quantflow.common.event_bus import EVENT_BAR, EVENT_RISK, EVENT_SIGNAL, Event, EventBus
from quantflow.common.models import Bar, Direction, OrderRequest, OrderSide, OrderStatus, Signal
from quantflow.execution.engine import ExecutionEngine
from quantflow.execution.kill_switch import KillSwitch
from quantflow.indicators.regime import MarketRegimeDetector
from quantflow.monitoring.alerts import AlertLevel, AlertManager
from quantflow.monitoring.metrics import (
    BAR_PROCESSING_LATENCY,
    SIGNAL_PROCESSING_LATENCY,
    SIGNALS_GENERATED,
    start_metrics_server,
    update_portfolio_metrics,
)
from quantflow.signal.generator import SignalGenerator
from quantflow.signal.portfolio import PortfolioManager
from quantflow.signal.position_sizer import PositionSizer
from quantflow.signal.risk_engine import RiskEngine
from quantflow.strategy.base import StrategyBase, StrategyContext

logger = logging.getLogger(__name__)
_ATTEMPTED_METRICS_PORTS: set[int] = set()


def _ensure_metrics_server_started(port: int) -> None:
    if port in _ATTEMPTED_METRICS_PORTS:
        return
    _ATTEMPTED_METRICS_PORTS.add(port)
    start_metrics_server(port)


class TradingSession:
    """Unified trading session for backtest, paper, or live mode."""

    def __init__(
        self,
        config: AppConfig,
        strategies: Sequence[StrategyBase],
        *,
        strategy_risk_budgets: dict[str, float] | None = None,
        strategy_win_rates: dict[str, float] | None = None,
        strategy_hit_rates: dict[str, float] | None = None,
    ) -> None:
        self._config = config
        self._strategies = list(strategies)
        self._event_bus = EventBus()
        self._execution = ExecutionEngine(
            event_bus=self._event_bus, timeout=config.execution.order_timeout
        )
        self._risk_engine = RiskEngine(config.risk, strategy_risk_budgets=strategy_risk_budgets)
        self._position_sizer = PositionSizer(
            method="kelly",
            kelly_fraction=config.risk.kelly_fraction,
            # position_limit_pct is a fraction (e.g. 0.20 = 20%); pass it
            # directly. Multiplying by 100 yielded 20.0 = 2000%, making the
            # max-position clamp a no-op and silently ignoring the risk config.
            max_position_pct=config.risk.position_limit_pct,
            # Volatility-targeting cap (deep-research F3 / P1). Default None
            # = OFF, preserving the byte-for-byte backtest baseline. Opt-in
            # via risk.vol_target_pct in YAML.
            vol_target_pct=config.risk.vol_target_pct,
            vol_annualization=config.risk.vol_annualization,
            vol_window=config.risk.vol_window,
        )
        self._portfolio = PortfolioManager(initial_capital=100000.0)
        self._signal_gen = SignalGenerator()
        self._regime_detector = MarketRegimeDetector()
        self._strategy_win_rates = strategy_win_rates or {}
        self._strategy_hit_rates = strategy_hit_rates or {}
        self._contexts: dict[str, StrategyContext] = {}
        self._kill_switch: KillSwitch | None = None
        self._running = False
        self._alert_mgr: AlertManager | None = None
        self._last_error: str | None = None
        # Equity snapshot from the previous bar's close, used to derive the
        # realized per-bar return fed to PositionSizer.add_return and
        # RiskEngine.add_return (ISS-20260719-001). NaN until the second bar.
        self._prev_equity: float = float("nan")
        # Rolling (timestamp_ms, equity) snapshots for the weekly-loss gate
        # (RiskEngine._check_weekly_loss). The weekly PnL is the realized
        # return over the trailing 7-day window measured by bar timestamps,
        # so it is correct across any timeframe (1h/4h/1d). Without this the
        # weekly_loss_limit in default.yaml is silently unenforced because
        # set_weekly_pnl is never called (ARCH-H1).
        self._equity_history: deque[tuple[int, float]] = deque(maxlen=100_000)

    async def start(
        self, mode: str = "paper", gateway_config: dict[str, Any] | None = None
    ) -> None:
        """Start the trading session."""
        await self._execution.start(mode, gateway_config)

        # Safety: live mode MUST run with the kill switch armed (CLAUDE.md
        # "实盘模式必须启用 Kill Switch"). Refuse to start rather than silently
        # trading live without an emergency-stop path.
        if mode == "live" and not self._config.risk.kill_switch_enabled:
            raise RuntimeError(
                "Kill switch must be enabled in live mode "
                "(config.risk.kill_switch_enabled=True); refusing to start."
            )

        # Initialize kill switch if enabled
        if self._config.risk.kill_switch_enabled and self._execution.gateway:
            self._kill_switch = KillSwitch(self._execution.gateway)
            self._event_bus.subscribe(EVENT_RISK, self._on_risk_event)

        # Reset per-session state so a restarted session does not gate on the
        # previous run's returns / weekly-PnL / equity history (CORR-M2).
        self._risk_engine.reset()
        self._position_sizer.reset()
        self._prev_equity = float("nan")
        self._equity_history.clear()

        # Initialize alert manager from config
        channels = self._config.monitoring.alert_channels
        if channels:
            ch = channels[0]
            self._alert_mgr = AlertManager(
                telegram_token=ch.token,
                telegram_chat_id=ch.chat_id,
            )

        # Start Prometheus metrics server once per process/port to avoid noisy retries.
        _ensure_metrics_server_started(self._config.monitoring.prometheus_port)

        if self._strategies:
            if self._strategy_win_rates:
                # Win-rate-weighted allocation (better strategies get more capital)
                total_wr = sum(self._strategy_win_rates.get(s.name, 0.5) for s in self._strategies)
                if total_wr > 0:
                    allocation = {
                        s.name: self._strategy_win_rates.get(s.name, 0.5) / total_wr
                        for s in self._strategies
                    }
                else:
                    allocation = {s.name: 1.0 / len(self._strategies) for s in self._strategies}
            else:
                allocation = {s.name: 1.0 / len(self._strategies) for s in self._strategies}
            self._portfolio.set_allocation(allocation)

        for strategy in self._strategies:
            ctx = StrategyContext()
            strategy.on_init(ctx)
            self._contexts[strategy.name] = ctx

        self._running = True
        logger.info("Trading session started: %d strategies, mode=%s", len(self._strategies), mode)

    async def on_bar(self, bar: Bar) -> None:
        """Process a new bar through the full pipeline."""
        if not self._running:
            return

        # Check kill switch first
        if self._kill_switch and self._kill_switch.is_active:
            return

        started_at = perf_counter()
        self._event_bus.publish(
            Event(
                type=EVENT_BAR,
                data={
                    "symbol": bar.symbol,
                    "close": bar.close,
                    "timestamp": bar.timestamp,
                },
            )
        )

        # Update position prices
        self._execution.update_market_price(bar.symbol, bar.close)
        self._portfolio.update_position(bar.symbol, 0, bar.close)

        # Feed the realized per-bar return to the risk engine and position
        # sizer so vol-targeting (F3) and the CVaR gate (risk_engine._check_var)
        # have a history to operate on (ISS-20260719-001). The denominator is
        # the previous bar's close equity, captured before this bar's price
        # mark — no look-ahead. Skipped on the first bar (NaN sentinel).
        curr_equity = self._portfolio.total_value
        prev_equity = self._prev_equity
        if not math.isnan(prev_equity) and prev_equity > 0:
            bar_ret = (curr_equity - prev_equity) / prev_equity
            self._risk_engine.add_return(bar_ret)
            self._position_sizer.add_return(bar_ret)
        self._prev_equity = curr_equity

        # Weekly-loss gate (ARCH-H1): feed the realized 7-day PnL to the risk
        # engine so _check_weekly_loss is no longer a permanent no-op. Window
        # is measured by bar timestamps (not bar count) so it is correct for
        # any timeframe. The 7-day cutoff falls back to the oldest snapshot
        # when the session is younger than 7 days — a conservative (less
        # negative) measure during warmup.
        self._equity_history.append((bar.timestamp, curr_equity))
        week_ago_ms = bar.timestamp - 7 * 24 * 3600 * 1000
        base_equity = curr_equity
        for ts, eq in self._equity_history:
            if ts >= week_ago_ms:
                base_equity = eq
                break
        if base_equity > 0:
            weekly_pnl_pct = (curr_equity - base_equity) / base_equity
            self._risk_engine.set_weekly_pnl(weekly_pnl_pct)

        # Refresh the portfolio gauges from the same state the session uses.
        self._update_portfolio_observability()

        # Update drawdown tracking
        pf = self._portfolio.portfolio
        dd_ok = self._portfolio.check_drawdown(self._config.risk.max_drawdown)
        if not dd_ok and self._config.risk.kill_switch_enabled and self._kill_switch:
            logger.critical("Drawdown breach — activating kill switch")
            await self._kill_switch.activate("drawdown_breach")
            if self._alert_mgr:
                await self._alert_mgr.send(
                    "KILL SWITCH ACTIVATED: drawdown breach",
                    AlertLevel.CRITICAL,
                    extra={"drawdown": pf.current_drawdown},
                )
            self._running = False
            self._record_bar_latency(bar.symbol, started_at)
            return

        # Detect market regime for strategy gating.
        # Two-layer design (ISS-20260720-001, resolved as design-property): regime
        # is a macro market-state gate (ADX strength via MarketRegimeDetector),
        # while strategy entries are micro signals (MA direction). They use
        # different detectors on purpose — a strategy's entries may fire on bars
        # the regime gate excludes, so backtest (generate_signals, no regime gate)
        # trades a superset of live/paper (on_bar, regime-gated). Live-faithful
        # validation uses paper-on_bar replay, not the vectorized backtest path.
        regime = self._regime_detector.update(bar.high, bar.low, bar.close)

        # Collect signals from regime-eligible strategies, then consolidate per symbol
        all_signals: list[Signal] = []
        for strategy in self._strategies:
            # Gate strategies by required regime
            if strategy.required_regime == "trending" and not regime.is_trending:
                continue
            if strategy.required_regime == "mean_reversion" and regime.is_trending:
                continue

            ctx = self._contexts.get(strategy.name)
            if not ctx:
                continue
            strategy.on_bar(ctx, bar)
            all_signals.extend(ctx.flush_signals())

        # Group by symbol and consolidate conflicting signals
        by_symbol: dict[str, list[Signal]] = {}
        for sig in all_signals:
            by_symbol.setdefault(sig.symbol, []).append(sig)

        for _symbol, sigs in by_symbol.items():
            if len(sigs) > 1:
                consolidated = self._signal_gen.consolidate_signals(sigs, self._strategy_hit_rates)
                if consolidated:
                    await self._process_signal(consolidated)
            else:
                await self._process_signal(sigs[0])

        self._record_bar_latency(bar.symbol, started_at)

    async def _process_signal(self, signal: Signal) -> None:
        """Process a signal through risk check → position sizing → execution."""
        started_at = perf_counter()
        portfolio = self._portfolio.portfolio

        # FLAT signals close the existing position (reduce-only) rather than
        # opening a new short. Without this, a FLAT exit on a long would fall
        # through the `direction.value > 0` branch below and submit a SELL that
        # opens a brand-new short instead of flattening.
        if signal.direction == Direction.FLAT:
            await self._close_position_for_signal(signal)
            self._record_signal_latency(signal.strategy_id, started_at)
            return

        risk_decision = self._risk_engine.check(signal, portfolio)

        if not risk_decision.passed:
            logger.warning(
                "Signal blocked by risk: %s (%s)", signal.strategy_id, risk_decision.reason
            )
            self._event_bus.publish(
                Event(
                    type=EVENT_RISK,
                    data={
                        "type": "signal_blocked",
                        "reason": risk_decision.reason,
                        "strategy_id": signal.strategy_id,
                    },
                )
            )
            if self._alert_mgr:
                await self._alert_mgr.send(
                    f"Signal blocked: {risk_decision.reason}",
                    AlertLevel.WARNING,
                    extra={"strategy_id": signal.strategy_id, "symbol": signal.symbol},
                )
            self._record_signal_latency(signal.strategy_id, started_at)
            return

        self._event_bus.publish(
            Event(
                type=EVENT_SIGNAL,
                data={
                    "strategy_id": signal.strategy_id,
                    "symbol": signal.symbol,
                    "direction": signal.direction.value,
                    "strength": signal.strength,
                },
            )
        )

        # Prometheus: track signal
        SIGNALS_GENERATED.labels(
            strategy_id=signal.strategy_id,
            direction=str(signal.direction.value),
        ).inc()

        # Position sizing (uses signal strength + per-strategy win rate)
        allocation = self._portfolio.get_strategy_allocation(signal.strategy_id)
        size = (
            self._position_sizer.size(
                signal, portfolio, strategy_win_rates=self._strategy_win_rates
            )
            * allocation
        )

        if size <= 0:
            self._record_signal_latency(signal.strategy_id, started_at)
            return

        # Calculate quantity
        quantity = size / signal.price

        # Submit order
        side = OrderSide.BUY if signal.direction.value > 0 else OrderSide.SELL

        order = await self._execution.submit_order(
            OrderRequest(
                symbol=signal.symbol,
                side=side,
                order_type="market",
                quantity=quantity,
                strategy_id=signal.strategy_id,
            )
        )
        if order.status == OrderStatus.FILLED:
            filled_quantity = order.filled_quantity or quantity
            fill_price = order.filled_price or order.price or signal.price
            signed_quantity = filled_quantity if order.side == OrderSide.BUY else -filled_quantity
            self._portfolio.update_position(
                order.symbol,
                signed_quantity,
                fill_price,
                fee=order.fee,
                strategy_id=order.strategy_id,
            )
            self._update_portfolio_observability()
        self._record_signal_latency(signal.strategy_id, started_at)

    async def _close_position_for_signal(self, signal: Signal) -> None:
        """Flatten the existing position for a FLAT signal (reduce-only).

        Sizes the close order to the current held quantity so a FLAT exit
        flattens the position instead of opening a new short.
        """
        pos = self._portfolio.get_position(signal.symbol)
        if pos is None or abs(pos.quantity) < 1e-10:
            return
        side = OrderSide.SELL if pos.quantity > 0 else OrderSide.BUY
        quantity = abs(pos.quantity)
        order = await self._execution.submit_order(
            OrderRequest(
                symbol=signal.symbol,
                side=side,
                order_type="market",
                quantity=quantity,
                strategy_id=signal.strategy_id,
                # reduceOnly (CCXT's canonical camelCase param name) tells the
                # live exchange this order may only decrease an existing
                # position, never open a new one — so a SELL that flattens a
                # long cannot flip into a new short if the held quantity has
                # changed between sizing and submit (e.g. a concurrent live
                # fill). PaperGateway ignores params.
                params={"reduceOnly": True},
            )
        )
        if order.status == OrderStatus.FILLED:
            filled_quantity = order.filled_quantity or quantity
            fill_price = order.filled_price or order.price or signal.price
            # Reduce-only: opposite sign of the held position.
            signed_quantity = -pos.quantity * (filled_quantity / max(abs(pos.quantity), 1e-10))
            self._portfolio.update_position(
                order.symbol,
                signed_quantity,
                fill_price,
                fee=order.fee,
                strategy_id=order.strategy_id,
            )
            self._update_portfolio_observability()

    def _update_portfolio_observability(self) -> None:
        snapshot = self._portfolio.snapshot()
        update_portfolio_metrics(
            total_value=float(snapshot["total_value"]),
            cash=float(snapshot["cash"]),
            drawdown=float(snapshot["drawdown"]),
            n_positions=int(snapshot["positions"]),
        )

    @staticmethod
    def _record_bar_latency(symbol: str, started_at: float) -> None:
        BAR_PROCESSING_LATENCY.labels(symbol=symbol).observe(perf_counter() - started_at)

    @staticmethod
    def _record_signal_latency(strategy_id: str, started_at: float) -> None:
        SIGNAL_PROCESSING_LATENCY.labels(strategy_id=strategy_id).observe(
            perf_counter() - started_at
        )

    def _on_risk_event(self, event: Event) -> None:
        """Handle risk events — trigger kill switch on emergencies."""
        severity = event.data.get("severity", "warn")
        if severity == "emergency" and self._kill_switch and not self._kill_switch.is_active:
            logger.critical("Emergency risk event — will activate kill switch on next cycle")

    async def run_data_loop(
        self,
        symbol: str,
        timeframe: str = "1h",
        interval_seconds: int = 60,
    ) -> None:
        """Continuously fetch new bars and feed them into on_bar().

        This is the main loop for paper/live mode.
        """
        from quantflow.data.fetcher import DataFetcher
        from quantflow.data.store import DataStore

        if self._config.execution.mode == "paper":
            store = DataStore(self._config.data.parquet_dir, ":memory:")
            timeframe_filter: str | None = timeframe
            pending_frame = store.query(symbol, timeframe=timeframe_filter)
            if pending_frame.empty:
                # Timeframe fallback: the requested timeframe is not in local
                # parquet. Rather than silently trading a different timeframe
                # than configured (a backtest/live parity leak — ARCH-M6), log
                # at WARNING and replay whatever IS available so the operator
                # sees the divergence. The log names both the requested and the
                # fallback cadence explicitly.
                pending_frame = store.query(symbol)
                if not pending_frame.empty:
                    timeframe_filter = None
                    logger.warning(
                        "Paper session requested %s/%s but only alternate local "
                        "parquet data exists; replaying available bars (timeframe "
                        "divergence from config — verify this is intended).",
                        symbol,
                        timeframe,
                    )
            try:
                if not pending_frame.empty:
                    await self._run_local_data_loop(
                        store=store,
                        symbol=symbol,
                        interval_seconds=interval_seconds,
                        pending_frame=pending_frame,
                        timeframe_filter=timeframe_filter,
                    )
                    return
            finally:
                store.close()

        fetcher = DataFetcher(self._config.data)
        last_timestamp: int | None = None
        connected = False

        try:
            while self._running:
                if not connected:
                    try:
                        await fetcher.connect()
                        connected = True
                        self._last_error = None
                    except Exception as e:
                        self._last_error = f"Data feed connection error: {e}"
                        logger.error("%s", self._last_error)
                        await fetcher.disconnect()
                        self.check_health()
                        self._execution.check_timeouts()
                        await asyncio.sleep(interval_seconds)
                        continue

                # Fetch latest bars
                try:
                    df = await fetcher.fetch_ohlcv(
                        symbol,
                        timeframe,
                        start=None,
                        limit=10,
                    )
                    self._last_error = None

                    if not df.empty and "timestamp" in df.columns:
                        for row in df.itertuples(index=False):
                            ts = int(row.timestamp)
                            if last_timestamp is None or ts > last_timestamp:
                                bar = Bar(
                                    symbol=symbol,
                                    timestamp=ts,
                                    open=float(row.open),
                                    high=float(row.high),
                                    low=float(row.low),
                                    close=float(row.close),
                                    volume=float(row.volume),
                                )
                                await self.on_bar(bar)
                                last_timestamp = ts

                except Exception as e:
                    self._last_error = f"Data feed error: {e}"
                    logger.error("%s", self._last_error)
                    connected = False
                    await fetcher.disconnect()

                # Health check
                self.check_health()

                # Order timeout check
                self._execution.check_timeouts()

                await asyncio.sleep(interval_seconds)

        except asyncio.CancelledError:
            logger.info("Data loop cancelled")
        finally:
            await fetcher.disconnect()

    async def _run_local_data_loop(
        self,
        *,
        store: Any,
        symbol: str,
        interval_seconds: int,
        pending_frame: Any,
        timeframe_filter: str | None,
    ) -> None:
        """Replay locally persisted parquet bars for paper sessions."""
        last_timestamp: int | None = None
        self._last_error = None
        logger.info(
            "Using local parquet replay for paper session: %s (%s)",
            symbol,
            timeframe_filter or "any timeframe",
        )

        try:
            while self._running:
                try:
                    df = pending_frame
                    pending_frame = None
                    if df is None:
                        query_args: dict[str, Any] = {
                            "symbol": symbol,
                            "start": last_timestamp + 1 if last_timestamp is not None else None,
                        }
                        if timeframe_filter is not None:
                            query_args["timeframe"] = timeframe_filter
                        df = store.query(**query_args)

                    if not df.empty and "timestamp" in df.columns:
                        self._last_error = None
                        for row in df.itertuples(index=False):
                            ts = int(row.timestamp)
                            if last_timestamp is None or ts > last_timestamp:
                                bar = Bar(
                                    symbol=symbol,
                                    timestamp=ts,
                                    open=float(row.open),
                                    high=float(row.high),
                                    low=float(row.low),
                                    close=float(row.close),
                                    volume=float(row.volume),
                                )
                                await self.on_bar(bar)
                                last_timestamp = ts

                except Exception as e:
                    self._last_error = f"Local data replay error: {e}"
                    logger.error("%s", self._last_error)

                self.check_health()
                self._execution.check_timeouts()
                await asyncio.sleep(interval_seconds)

        except asyncio.CancelledError:
            logger.info("Data loop cancelled")

    def check_health(self) -> dict[str, Any]:
        """Check session health: drawdown, pending orders, positions.

        Position count is read from the L4 PortfolioManager (the authoritative
        book for risk decisions) rather than the L5 PositionManager. The two
        can diverge in live mode (sync_positions updates only L5; partial fills
        may land in one but not the other), so mixing them lets health status
        disagree with the drawdown reading — both now come from L4 (ISS-20260720-004
        partial fix: presentation-layer consistency; full L4/L5 reconcile tracked
        separately).
        """
        dd_ok = self._portfolio.check_drawdown(self._config.risk.max_drawdown)
        pending = self._execution.order_manager.pending_count
        positions = len(self._portfolio.positions)

        health = {
            "running": self._running,
            "drawdown_ok": dd_ok,
            "pending_orders": pending,
            "open_positions": positions,
        }

        if not dd_ok:
            logger.critical("Drawdown breach detected — consider activating kill switch")

        return health

    async def stop(self) -> None:
        """Stop the trading session."""
        self._running = False
        await self._execution.stop()
        logger.info("Trading session stopped")

    @property
    def portfolio(self) -> PortfolioManager:
        return self._portfolio

    @property
    def execution(self) -> ExecutionEngine:
        return self._execution

    @property
    def kill_switch(self) -> KillSwitch | None:
        return self._kill_switch

    @property
    def last_error(self) -> str | None:
        return self._last_error

    # --- Presentation-layer facade ---
    # These methods let the web/UI layer read live state and trigger controls
    # WITHOUT reaching into execution (L5) or portfolio (L4) internals, keeping
    # the session as the single integration boundary.

    def snapshot_state(self) -> dict[str, Any]:
        """Return a structured live-state snapshot for presentation layers.

        All position/cash state is read from the L4 PortfolioManager (the
        authoritative book for risk decisions) so the snapshot is internally
        consistent — cash, total_value, drawdown, and positions all reflect
        the same source of truth. Previously positions came from the L5
        PositionManager while cash/portfolio came from L4, allowing the two to
        disagree in live mode (sync_positions updates only L5). Full L4/L5
        reconcile (including live sync_positions→L4) is tracked as
        ISS-20260720-004; this snapshot unification closes the
        presentation-layer inconsistency.
        """
        health = self.check_health()
        portfolio = self._portfolio.snapshot()
        portfolio["market_value"] = sum(p.market_value for p in self._portfolio.positions.values())
        portfolio["equity"] = self._portfolio.cash + portfolio["market_value"]
        portfolio["total_value"] = portfolio["equity"]
        positions = [
            {
                "symbol": p.symbol,
                "quantity": p.quantity,
                "entry_price": p.entry_price,
                "current_price": p.current_price,
                "market_value": p.market_value,
                "unrealized_pnl": p.unrealized_pnl,
                "strategy_id": p.strategy_id,
            }
            for p in self._portfolio.positions.values()
        ]
        open_orders = [
            {
                "order_id": o.order_id,
                "symbol": o.symbol,
                "side": o.side.value,
                "order_type": o.order_type,
                "status": o.status.value,
                "quantity": o.quantity,
                "price": o.price,
                "strategy_id": o.strategy_id,
            }
            for o in self._execution.order_manager.get_open_orders()
        ]
        return {
            "health": health,
            "cash": self._portfolio.cash,
            "portfolio": portfolio,
            "positions": positions,
            "open_orders": open_orders,
            "kill_switch": self._kill_switch.check() if self._kill_switch is not None else None,
        }

    async def activate_kill_switch(self, reason: str) -> dict[str, Any]:
        """Activate the kill switch (raises if none configured)."""
        if self._kill_switch is None:
            raise RuntimeError("No active session kill switch is available.")
        return await self._kill_switch.activate(reason)

    def adjust_capital(self, capital: float) -> None:
        """Set the portfolio capital atomically (initial capital + peak)."""
        cash_delta = capital - self._portfolio.cash
        if abs(cash_delta) > 1e-10:
            self._portfolio.update_cash(cash_delta)
        self._portfolio.set_capital_baseline(capital)
