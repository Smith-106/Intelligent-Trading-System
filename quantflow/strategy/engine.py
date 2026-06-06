"""Trading Session — orchestrates a complete trading session.

Manages the lifecycle: data feed → strategy → signal → risk → execution.
Supports backtest, paper, and live modes with the same strategy code.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from time import perf_counter
from typing import Any

from quantflow.common.config import AppConfig
from quantflow.common.event_bus import EVENT_BAR, EVENT_RISK, EVENT_SIGNAL, Event, EventBus
from quantflow.common.models import Bar, OrderRequest, OrderSide, Signal
from quantflow.execution.engine import ExecutionEngine
from quantflow.execution.kill_switch import KillSwitch
from quantflow.monitoring.alerts import AlertLevel, AlertManager
from quantflow.monitoring.metrics import (
    BAR_PROCESSING_LATENCY,
    SIGNAL_PROCESSING_LATENCY,
    SIGNALS_GENERATED,
    start_metrics_server,
    update_portfolio_metrics,
)
from quantflow.signal.portfolio import PortfolioManager
from quantflow.signal.position_sizer import PositionSizer
from quantflow.signal.risk_engine import RiskEngine
from quantflow.strategy.base import StrategyBase, StrategyContext

logger = logging.getLogger(__name__)


class TradingSession:
    """Unified trading session for backtest, paper, or live mode."""

    def __init__(self, config: AppConfig, strategies: Sequence[StrategyBase]) -> None:
        self._config = config
        self._strategies = list(strategies)
        self._event_bus = EventBus()
        self._execution = ExecutionEngine(
            event_bus=self._event_bus, timeout=config.execution.order_timeout
        )
        self._risk_engine = RiskEngine(config.risk)
        self._position_sizer = PositionSizer(
            method="kelly",
            kelly_fraction=0.5,
            max_position_pct=config.risk.position_limit_pct * 100,
        )
        self._portfolio = PortfolioManager(initial_capital=100000.0)
        self._contexts: dict[str, StrategyContext] = {}
        self._kill_switch: KillSwitch | None = None
        self._running = False
        self._alert_mgr: AlertManager | None = None

    async def start(
        self, mode: str = "paper", gateway_config: dict[str, Any] | None = None
    ) -> None:
        """Start the trading session."""
        await self._execution.start(mode, gateway_config)

        # Initialize kill switch if enabled
        if self._config.risk.kill_switch_enabled and self._execution.gateway:
            self._kill_switch = KillSwitch(self._execution.gateway)
            self._event_bus.subscribe(EVENT_RISK, self._on_risk_event)

        # Initialize alert manager from config
        channels = self._config.monitoring.alert_channels
        if channels:
            ch = channels[0]
            self._alert_mgr = AlertManager(
                telegram_token=ch.token,
                telegram_chat_id=ch.chat_id,
            )

        # Start Prometheus metrics server
        start_metrics_server(self._config.monitoring.prometheus_port)

        if self._strategies:
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
        self._execution.position_manager.update_market_price(bar.symbol, bar.close)
        self._portfolio.update_position(bar.symbol, 0, bar.close)

        # Update Prometheus portfolio metrics
        pf = self._portfolio.portfolio
        total_value = pf.total_value
        update_portfolio_metrics(
            total_value=total_value,
            cash=pf.cash,
            drawdown=pf.current_drawdown,
            n_positions=len(pf.positions),
        )

        # Update drawdown tracking
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

        for strategy in self._strategies:
            ctx = self._contexts.get(strategy.name)
            if not ctx:
                continue

            strategy.on_bar(ctx, bar)
            signals = ctx.flush_signals()

            for signal in signals:
                await self._process_signal(signal)

        self._record_bar_latency(bar.symbol, started_at)

    async def _process_signal(self, signal: Signal) -> None:
        """Process a signal through risk check → position sizing → execution."""
        started_at = perf_counter()
        portfolio = self._portfolio.portfolio
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

        # Position sizing (uses signal strength)
        allocation = self._portfolio.get_strategy_allocation(signal.strategy_id)
        size = self._position_sizer.size(signal, portfolio) * allocation

        if size <= 0:
            self._record_signal_latency(signal.strategy_id, started_at)
            return

        # Calculate quantity
        quantity = size / signal.price

        # Submit order
        side = OrderSide.BUY if signal.direction.value > 0 else OrderSide.SELL

        await self._execution.submit_order(
            OrderRequest(
                symbol=signal.symbol,
                side=side,
                order_type="market",
                quantity=quantity,
                strategy_id=signal.strategy_id,
            )
        )
        self._record_signal_latency(signal.strategy_id, started_at)

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

        fetcher = DataFetcher(self._config.data)
        last_timestamp: int | None = None
        connected = False

        try:
            while self._running:
                if not connected:
                    try:
                        await fetcher.connect()
                        connected = True
                    except Exception as e:
                        logger.error("Data feed connection error: %s", e)
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
                    logger.error("Data fetch error: %s", e)
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

    def check_health(self) -> dict[str, Any]:
        """Check session health: drawdown, pending orders, positions."""
        dd_ok = self._portfolio.check_drawdown(self._config.risk.max_drawdown)
        pending = self._execution.order_manager.pending_count
        positions = self._execution.position_manager.position_count

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
