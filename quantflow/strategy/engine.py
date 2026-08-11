"""Trading Session — orchestrates a complete trading session.

Manages the lifecycle: data feed → strategy → signal → risk → execution.
Supports backtest, paper, and live modes with the same strategy code.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import time
from collections.abc import Sequence
from time import perf_counter
from typing import Any

from quantflow.common.config import AppConfig
from quantflow.common.event_bus import EVENT_BAR, EVENT_RISK, EVENT_SIGNAL, Event, EventBus
from quantflow.common.models import (
    Bar,
    Direction,
    OrderRequest,
    OrderSide,
    OrderStatus,
    Position,
    Signal,
    strategy_id_constituents,
)
from quantflow.common.monitoring_sink import MonitoringSink, NullMonitoringSink
from quantflow.common.redaction import redact_secrets
from quantflow.common.validators import POSITION_EPSILON
from quantflow.execution.engine import ExecutionEngine
from quantflow.execution.kill_switch import KillSwitch
from quantflow.execution.state_store import SessionSnapshot, StateStore
from quantflow.indicators.regime import MarketRegimeDetector
from quantflow.reconciliation.engine import ReconciliationEngine
from quantflow.signal.generator import SignalGenerator
from quantflow.signal.optimizer import MeanVarianceOptimizer, RiskParityOptimizer
from quantflow.signal.portfolio import PortfolioManager
from quantflow.signal.position_sizer import PositionSizer
from quantflow.signal.risk_engine import RiskEngine
from quantflow.strategy.base import StrategyBase, StrategyContext

logger = logging.getLogger(__name__)

# Backward-compat shim (ISS-019): the metrics-server dedup moved into
# monitoring.metrics.start_metrics_server (idempotent per port) and the live
# start path now goes through ``self._sink.start(config)``. Several tests
# monkeypatch ``engine._ensure_metrics_server_started`` /
# ``_ATTEMPTED_METRICS_PORTS``; keep the names importable so those patches
# still resolve. The shim is intentionally a no-op — it must not re-introduce a
# top-level ``monitoring`` import (the L3->L6 coupling this refactor removes).
_ATTEMPTED_METRICS_PORTS: set[int] = set()


def _ensure_metrics_server_started(port: int) -> None:
    """Deprecated no-op — metrics start moved to MonitoringSink.start (ISS-019)."""
    return


_WEEK_MS = 7 * 24 * 3600 * 1000

# T-s2-04: meta-feed event types (plan locked: defined locally here; do NOT
# extend common/event_bus.py with feed-telemetry events).
EVENT_FUNDING = "funding"
EVENT_OI = "open_interest"
#: Idle sleep between meta-feed scheduling cycles (seconds). The actual
#: per-endpoint cadence is governed by FUNDING_POLL_INTERVAL_S /
#: OI_POLL_INTERVAL_S deadlines; this only sets the check granularity.
_META_FEED_SLEEP_S = 5.0


def _weekly_base_equity(
    history: list[tuple[int, float]],
    base_idx: int,
    now_ms: int,
) -> tuple[float, int, int]:
    """Find the equity snapshot anchoring the 7-day weekly-loss window.

    ISS-033: replaces an O(n) per-bar linear scan with an O(1) amortized
    monotone-forward pointer. ``history`` holds ``(timestamp_ms, equity)``
    pairs with monotonically non-decreasing timestamps; ``base_idx`` is the
    pointer carried across bars. Because ``now_ms - WEEK_MS`` is monotone,
    the first snapshot with ``ts >= week_ago`` only moves forward, so the
    pointer advances but never retreats (except by one on left-eviction,
    handled by the caller).

    Returns ``(base_equity, new_base_idx)``-ish triple: the anchor equity
    (falling back to the newest snapshot during warmup / empty history), the
    advanced pointer, and the week-ago cutoff (exposed for assertions).
    """
    week_ago_ms = now_ms - _WEEK_MS
    while base_idx < len(history) and history[base_idx][0] < week_ago_ms:
        base_idx += 1
    if base_idx < len(history):
        base_equity = history[base_idx][1]
    elif history:
        base_equity = history[-1][1]
    else:
        base_equity = 0.0
    return base_equity, base_idx, week_ago_ms


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
        monitoring_sink: MonitoringSink | None = None,
    ) -> None:
        self._config = config
        self._strategies = list(strategies)
        self._event_bus = EventBus()
        # L3->L6 seam (ISS-019 + ISS-20260724-044): TradingSession depends on
        # the MonitoringSink Protocol (common/) only. The concrete sink
        # (DefaultMonitoringSink from monitoring/) is injected by the caller
        # (cli / session_manager); defaulting to Null keeps backtest/tests
        # zero-observability with no L6 import on this path. Set BEFORE
        # constructing ExecutionEngine/RiskEngine so it can be threaded down
        # to the L4/L5 siblings (ISS-20260724-044).
        self._sink: MonitoringSink = monitoring_sink or NullMonitoringSink()
        # T-s1-04: exchange-level circuit breaker (opt-in via
        # config.risk.exchange_health.enabled; None = disabled keeps existing
        # runs byte-for-byte). One shared instance feeds RiskEngine (checks)
        # and ExecutionEngine → OKXGateway (REST/WS outcome recording).
        self._exchange_health: Any | None = None
        eh_cfg = config.risk.exchange_health
        if eh_cfg.enabled:
            from quantflow.execution.exchange_health import ExchangeHealthMonitor

            self._exchange_health = ExchangeHealthMonitor(
                window_seconds=eh_cfg.window_seconds,
                error_rate_threshold=eh_cfg.error_rate_threshold,
                rate_limit_streak_threshold=eh_cfg.rate_limit_streak,
                cooldown_seconds=eh_cfg.cooldown_seconds,
                monitoring_sink=self._sink,
                event_bus=self._event_bus,
            )
        self._execution = ExecutionEngine(
            event_bus=self._event_bus,
            timeout=config.execution.order_timeout,
            monitoring_sink=self._sink,
            health_monitor=self._exchange_health,
        )
        book_budget = None
        brb = getattr(config.risk, "book_risk_budget", None)
        if brb is not None and getattr(brb, "enabled", False):
            from quantflow.signal.book_risk_budget import BookRiskBudget

            book_budget = BookRiskBudget(
                book_gross_limit=float(brb.book_gross_limit),
                book_net_limit=float(brb.book_net_limit),
                kill_drawdown=float(brb.kill_drawdown),
                factor_sleeve_limits={
                    "beta": float(brb.beta_sleeve),
                    "overlay": float(brb.overlay_sleeve),
                },
            )
        self._risk_engine = RiskEngine(
            config.risk,
            strategy_risk_budgets=strategy_risk_budgets,
            monitoring_sink=self._sink,
            exchange_health=self._exchange_health,
            exchange_exposure_limit_pct=config.risk.exchange_exposure_limit_pct,
            book_risk_budget=book_budget,
        )
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
            # PositionSizer sizing 阈值（原硬编码 0.10/10.0，ISS-20260721-012 config-source）。
            # 默认值对齐硬编码保 byte-for-byte backtest baseline。
            fixed_pct=config.risk.fixed_pct,
            min_order_notional=config.risk.min_order_notional,
            # fee_rate 走 config.execution.taker_fee（D3：复用 execution 层 fee 真理源，
            # 默认 0.001 == 原硬编码，single-source-of-truth 消 YAML-schema-drift 重现）。
            fee_rate=config.execution.taker_fee,
        )
        self._portfolio = PortfolioManager(initial_capital=100000.0)
        # s5 (T-s5-02): portfolio-level risk-parity allocation. Default OFF
        # (enabled=False) — None optimizer = zero per-bar overhead and the
        # static allocation path unchanged. When enabled, per-strategy
        # returns are tracked in the bar loop and weights are recomputed
        # every ``rebalance_every_n_bars`` bars.
        _po_cfg = config.risk.portfolio_optimization
        if _po_cfg.enabled:
            # s5 follow-up: method-selectable optimizer (risk_parity default,
            # mean_variance opt-in). Both share the compute() contract and
            # degrade to equal weights on any failure (fail-closed).
            if _po_cfg.method == "mean_variance":
                self._portfolio_optimizer: RiskParityOptimizer | MeanVarianceOptimizer | None = (
                    MeanVarianceOptimizer(min_samples=_po_cfg.min_samples)
                )
            else:
                self._portfolio_optimizer = RiskParityOptimizer(min_samples=_po_cfg.min_samples)
        else:
            self._portfolio_optimizer = None
        self._rebalance_every_n_bars: int = _po_cfg.rebalance_every_n_bars if _po_cfg.enabled else 0
        # Grain of portfolio_optimization: strategy (s5 default) or symbol
        # (shared-book multi-asset risk parity). Invalid values fall back to
        # strategy so misconfig never silently disables sizing.
        self._portfolio_opt_level: str = (
            _po_cfg.level if _po_cfg.level in ("strategy", "symbol") else "strategy"
        )
        self._bar_count: int = 0
        # Previous bar's per-strategy notional exposure, for per-strategy
        # return attribution (s5). Empty dict on the default path.
        self._strategy_value_prev: dict[str, float] = {}
        # Previous bar's per-symbol notional (legacy position-based; unused for
        # symbol-level RP which tracks close-to-close returns instead).
        self._symbol_value_prev: dict[str, float] = {}
        # Symbol-level RP: last close per symbol (universe vol, not just held).
        self._symbol_close_prev: dict[str, float] = {}
        # Rebalance cadence counts unique bar timestamps so multi-symbol
        # interleaving does not accelerate rebalance 3× on a 3-symbol book.
        self._rebalance_ts_count: int = 0
        self._rebalance_last_ts: int | None = None
        # ISS-20260720-004 Wave 2: ExecutionEngine was constructed before
        # PortfolioManager existed; rebind its PositionManager to the shared L4
        # so submit()'s fill updates land on the same book the signal path reads.
        self._execution.set_portfolio(self._portfolio)
        self._signal_gen = SignalGenerator()
        # Per-symbol regime detectors. A single shared detector mixes OHLC from
        # different symbols and corrupts ADX (multi-symbol paper/live bug).
        self._regime_detectors: dict[str, MarketRegimeDetector] = {}
        self._strategy_win_rates = strategy_win_rates or {}
        self._strategy_hit_rates = strategy_hit_rates or {}
        # M4-2.2: contexts keyed by (strategy_name, symbol) for multi-symbol
        # isolation. Single-symbol mode uses (name, symbol) with one symbol.
        self._contexts: dict[tuple[str, str], StrategyContext] = {}
        # M4-2.1/2.2: per-(strategy, symbol) instances created by start() via
        # the strategy factory. Prototypes in _strategies are cloned per symbol
        # so each instance maintains independent state (_bars, EMA, _in_position).
        self._instances: dict[tuple[str, str], StrategyBase] = {}
        self._symbols: list[str] = []
        # M4-3.1: serialize the risk-check → sizing → submit critical section.
        # Prevents concurrent signals (multi-symbol gather) from seeing stale
        # portfolio snapshots between check and submit (TOCTOU guard, layer 1).
        # Lock covers ONLY _process_signal — data fetch and strategy computation
        # remain fully concurrent.
        self._signal_lock = asyncio.Lock()
        self._kill_switch: KillSwitch | None = None
        self._running = False
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
        # ISS-033: list (not deque) so timestamps are O(1)-indexable for the
        # bisect-based weekly-base lookup below. Manual maxlen eviction keeps
        # memory bounded; the amortized weekly-base pointer advances forward
        # only (week_ago_ms is monotonic in the bar clock), so each bar pays
        # O(1) amortized instead of the prior O(n) linear scan.
        self._equity_history: list[tuple[int, float]] = []
        self._equity_history_maxlen = 100_000
        self._weekly_base_idx = 0
        # ISS-20260720-004 Wave 3: daily-loss baseline anchor. Anchored to the
        # first bar's equity of each calendar day (UTC day index); NaN/None
        # means "not yet anchored today" so _check_daily_loss skips the gate
        # (warmup). Mirrors the _equity_history pattern but keyed on calendar
        # day rather than a 7-day window.
        self._daily_baseline: float = float("nan")
        self._daily_baseline_day: int | None = None
        # T-s1-03: crash-recovery state. _recovery_verified gates new-entry
        # signals after a checkpoint restore until reconciliation proves the
        # restored book matches the exchange (fail-closed). True by default —
        # sessions without a restored checkpoint trade normally.
        self._recovery_verified: bool = True
        self._session_mode: str = ""
        self._state_store: StateStore | None = None
        self._reconciliation_engine: ReconciliationEngine | None = None
        self._last_reconciliation_at: float = 0.0
        self._last_checkpoint_at: float = 0.0
        # T-s2-04: funding/OI meta feed state. _meta_feed_task runs only when
        # config.execution.funding_feed_enabled (default false → zero change).
        # _meta_fetcher is injectable so tests can feed scripted snapshots
        # without touching the network.
        self._meta_feed_task: asyncio.Task[None] | None = None
        self._meta_fetcher: Any | None = None
        self._dq_monitor: Any | None = None
        self._meta_fresh: dict[str, dict[str, Any]] = {}
        # W19b/W20a: optional ticker BBO cache + poll task.
        # push_ticker_bbo / _bbo_poll_loop; when bbo_source=ticker and a fresh
        # quote exists, on_bar prefers it over bar low/high proxy.
        self._ticker_bbo: dict[str, tuple[float, float]] = {}
        self._bbo_source: str = "bar_proxy"
        self._bbo_poll_task: asyncio.Task[None] | None = None
        self._bbo_fetcher: Any | None = None  # injectable DataFetcher for tests
        # W23a: optional trades ingest → TradesStore
        self._trades_ingest: Any | None = None
        self._trades_store: Any | None = None
        self._trades_fetcher: Any | None = None
        # W21a: session-level pause set for soft risk gates (funding, etc.)
        from quantflow.common.pause_reasons import PauseReasonSet

        self._risk_pauses = PauseReasonSet()
        self._last_funding_rate: dict[str, float] = {}

    async def start(
        self,
        mode: str = "paper",
        gateway_config: dict[str, Any] | None = None,
        symbols: list[str] | None = None,
    ) -> None:
        """Start the trading session.

        Args:
            mode: "paper", "live", or "okx".
            gateway_config: Gateway connection parameters.
            symbols: List of symbols to trade. If None, defaults to a single
                placeholder (backward compat — the data loop supplies the symbol
                via on_bar). When provided, per-(strategy, symbol) instances are
                created via the strategy factory (M4-2.1/2.2).
        """
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
            self._kill_switch = KillSwitch(self._execution.gateway, monitoring_sink=self._sink)
            # Wire the kill switch into the engine so submit() blocks new
            # orders the moment the switch is active, not only at on_bar entry
            # (odyssey-improve SEC-H4).
            self._execution.set_kill_switch(self._kill_switch)
            self._event_bus.subscribe(EVENT_RISK, self._on_risk_event)

        # Reset per-session state so a restarted session does not gate on the
        # previous run's returns / weekly-PnL / equity history (CORR-M2).
        self._risk_engine.reset()
        self._position_sizer.reset()
        self._prev_equity = float("nan")
        self._equity_history.clear()
        self._weekly_base_idx = 0
        # ISS-20260720-004 Wave 3: reset daily baseline so a restarted session
        # does not gate on the prior run's day anchor.
        self._daily_baseline = float("nan")
        self._daily_baseline_day = None
        self._portfolio.set_daily_baseline(float("nan"))

        # T-s1-03: crash-recovery restore. Contracted order (plan lock):
        # CORR-M2 reset FIRST (above), then restore, then strategy
        # instantiation (below) — a restore before the reset would be wiped,
        # after strategy instantiation would race on_bar state.
        self._recovery_verified = True
        self._session_mode = mode
        if self._config.state.enabled and mode in ("paper", "live"):
            self._state_store = StateStore(self._config.state.checkpoint_dir)
            snapshot = self._state_store.load_checkpoint()
            if snapshot is not None:
                self._restore_from_snapshot(snapshot)
                self._recovery_verified = await self._verify_recovery()
                logger.info(
                    "Checkpoint restored: verified=%s (cash=%.2f, %d positions)",
                    self._recovery_verified,
                    snapshot.cash,
                    len(snapshot.positions),
                )
            elif self._state_store.last_error is not None:
                # Corrupt checkpoint: fail-closed — refuse new entries until
                # an operator clears the checkpoint and restarts.
                self._recovery_verified = False
                logger.critical("Checkpoint corrupted — new-entry signals blocked (fail-closed)")
        if self._reconciliation_engine is None and self._config.reconciliation.enabled:
            # Periodic reconciliation without checkpoint restore (live wiring).
            self._build_reconciliation_engine()

        # Start observability via the injected sink (ISS-019): the sink owns
        # both the metrics-server start (idempotent per port) and the
        # AlertManager wiring — L3 no longer touches monitoring/ concrete
        # classes directly.
        self._sink.start(self._config)

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

        # M4-2.1/2.2: create per-(strategy, symbol) instances and contexts.
        # When symbols is provided, the factory clones each strategy per symbol
        # so internal state (_bars, EMA, _in_position) is isolated. When symbols
        # is None (legacy single-symbol callers), fall back to the original
        # behavior: one context per strategy keyed by (name, "").
        self._symbols = symbols or []
        if self._symbols:
            from quantflow.strategy.factory import create_all_per_symbol

            self._instances = create_all_per_symbol(self._strategies, self._symbols)
            for (name, symbol), instance in self._instances.items():
                ctx = StrategyContext()
                instance.on_init(ctx)
                self._contexts[(name, symbol)] = ctx
        else:
            # Legacy path: no symbols declared at start time. Contexts are
            # created per strategy with an empty-symbol key; on_bar will
            # lazily create (name, bar.symbol) contexts on first sight.
            self._instances = {}
            for strategy in self._strategies:
                ctx = StrategyContext()
                strategy.on_init(ctx)
                self._contexts[(strategy.name, "")] = ctx

        self._running = True
        # T-s2-04: opt-in funding/OI background feed (funding_feed_enabled in
        # execution config; default false keeps existing runs byte-for-byte).
        # Spawned AFTER instance creation so (funding_rate, symbol) targets
        # exist when the first samples land.
        if self._config.execution.funding_feed_enabled:
            self._meta_feed_task = asyncio.create_task(self._meta_feed_loop())
        # W20a: opt-in ticker BBO poll (default false). Switches source to ticker
        # so on_bar prefers polled quotes; orderbook_fill remains independently off.
        if getattr(self._config.execution, "bbo_poll_enabled", False):
            self.set_bbo_source("ticker")
            self._bbo_poll_task = asyncio.create_task(self._bbo_poll_loop())
        # W23a: opt-in trades poll into TradesStore (default false)
        if getattr(self._config.execution, "trades_poll_enabled", False):
            self._start_trades_ingest()
        logger.info(
            "Trading session started: %d strategies, %d symbols, mode=%s",
            len(self._strategies),
            len(self._symbols) or 1,
            mode,
        )

    def set_bbo_source(self, source: str) -> None:
        """W19b: select BBO source for paper fills — ``bar_proxy`` (default) or ``ticker``."""
        src = (source or "bar_proxy").strip().lower()
        if src not in ("bar_proxy", "ticker"):
            raise ValueError(f"bbo_source must be bar_proxy|ticker, got {source!r}")
        self._bbo_source = src

    def push_ticker_bbo(self, symbol: str, bid: float, ask: float) -> None:
        """W19b: cache a real ticker top-of-book quote for optional BBO fills."""
        try:
            b = float(bid)
            a = float(ask)
        except (TypeError, ValueError):
            return
        if b <= 0 or a <= 0 or b > a:
            return
        self._ticker_bbo[symbol] = (b, a)
        # Immediately forward so age gates see a fresh timestamp even between bars.
        if self._bbo_source == "ticker":
            self._execution.update_orderbook(symbol, bid=b, ask=a, mid_to_last=False)

    def _push_bbo_for_bar(self, bar: Bar) -> None:
        """Push BBO for this bar using configured source (W18b/W19b)."""
        if self._bbo_source == "ticker":
            quote = self._ticker_bbo.get(bar.symbol)
            if quote is not None:
                self._execution.update_orderbook(
                    bar.symbol, bid=quote[0], ask=quote[1], mid_to_last=False
                )
                return
            # Fall through to bar proxy when ticker cache is empty
        if bar.low > 0 and bar.high > 0 and bar.low <= bar.high:
            self._execution.update_orderbook(
                bar.symbol, bid=float(bar.low), ask=float(bar.high), mid_to_last=False
            )

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
        # W18b/W19b: push BBO so PaperGateway.update_orderbook has a caller.
        # Default source=bar_proxy (low/high). When bbo_source=ticker and a
        # quote was pushed via push_ticker_bbo, prefer that bid/ask.
        self._push_bbo_for_bar(bar)
        self._portfolio.update_position(bar.symbol, 0, bar.close)

        # Feed the realized per-bar return to the risk engine and position
        # sizer so vol-targeting (F3) and the CVaR gate (risk_engine._check_var)
        # have a history to operate on (ISS-20260719-001). The denominator is
        # the previous bar's close equity, captured before this bar's price
        # mark — no look-ahead. Skipped on the first bar (NaN sentinel).
        curr_equity = self._portfolio.total_value
        # ISS-20260720-004 Wave 3: daily-loss baseline anchor. On the first bar
        # of a calendar day (UTC day index from bar.timestamp in ms), anchor the
        # day's baseline to that bar's equity. _check_daily_loss reads
        # portfolio.daily_baseline (set here via the L4 method so the Portfolio
        # snapshot carries it to the pure-function RiskEngine). NaN baseline
        # means "not anchored" → warmup skip in the risk gate.
        current_day = bar.timestamp // 86_400_000
        if self._daily_baseline_day is None or current_day != self._daily_baseline_day:
            self._daily_baseline = curr_equity
            self._daily_baseline_day = current_day
            self._portfolio.set_daily_baseline(curr_equity)
        prev_equity = self._prev_equity
        if not math.isnan(prev_equity) and prev_equity > 0:
            bar_ret = (curr_equity - prev_equity) / prev_equity
            self._risk_engine.add_return(bar_ret)
            self._position_sizer.add_return(bar_ret)
        self._prev_equity = curr_equity

        # s5 (T-s5-02) + symbol-level RP: return attribution + periodic rebalance.
        # Only active when portfolio_optimization.enabled — default path skips
        # both entirely (zero behavior change).
        self._bar_count += 1
        if self._portfolio_optimizer is not None:
            if self._portfolio_opt_level == "symbol":
                # Universe close-to-close returns (not position notional): a
                # never-held symbol still accumulates vol history so RP can
                # assign it weight. Position-only attribution collapses to the
                # first traded name and locks others at weight 0.
                # Close tracking runs even on the first bar (prev_equity NaN)
                # so the second bar can form a return.
                prev_close = self._symbol_close_prev.get(bar.symbol)
                if prev_close is not None and prev_close > 0 and bar.close > 0:
                    ret = (bar.close - prev_close) / prev_close
                    self._portfolio.add_symbol_return(bar.symbol, ret)
                if bar.close > 0:
                    self._symbol_close_prev[bar.symbol] = float(bar.close)

                # Count unique timestamps for cadence (shared multi-symbol book).
                if self._rebalance_last_ts != bar.timestamp:
                    self._rebalance_last_ts = bar.timestamp
                    self._rebalance_ts_count += 1
                    should_rebalance = (
                        self._rebalance_every_n_bars > 0
                        and self._rebalance_ts_count % self._rebalance_every_n_bars == 0
                        and not math.isnan(prev_equity)
                    )
                else:
                    should_rebalance = False

                if should_rebalance:
                    returns = self._portfolio.get_symbol_returns()
                    weights = self._portfolio_optimizer.compute(returns)
                    self._portfolio.set_symbol_allocation(weights)
                    logger.info("s5 symbol rebalance: %s", weights)
                    try:
                        self._sink.record_portfolio_allocation(weights)
                    except Exception:  # sink contract: best-effort only
                        logger.exception("record_portfolio_allocation failed")
            elif not math.isnan(prev_equity):
                # Attribute this bar's return per strategy from notional exposure
                # changes (positions valued at the updated bar close).
                per_strategy_value: dict[str, float] = {}
                for pos in self._portfolio.positions.values():
                    if pos.current_price <= 0:
                        continue
                    constituents = strategy_id_constituents(pos.strategy_id) or [pos.strategy_id]
                    pos_value = abs(pos.quantity) * pos.current_price
                    for c in constituents:
                        per_strategy_value[c] = per_strategy_value.get(c, 0.0) + pos_value
                for sid, value in per_strategy_value.items():
                    prev_value = self._strategy_value_prev.get(sid, 0.0)
                    if prev_value > 0:
                        ret = (value - prev_value) / prev_value
                        self._portfolio.add_strategy_return(sid, ret)
                self._strategy_value_prev = per_strategy_value

                # Rebalance cadence: recompute risk-parity weights and push them
                # into the portfolio allocation consumed by PositionSizer.size().
                if self._bar_count % self._rebalance_every_n_bars == 0:
                    returns = self._portfolio.get_strategy_returns()
                    weights = self._portfolio_optimizer.compute(returns)
                    self._portfolio.set_allocation(weights)
                    logger.info("s5 rebalance: %s", weights)
                    # s5 follow-up: expose the rebalanced weights to monitoring
                    # (best-effort — sink must never raise into the bar loop).
                    try:
                        self._sink.record_portfolio_allocation(weights)
                    except Exception:  # sink contract: best-effort only
                        logger.exception("record_portfolio_allocation failed")

        # Weekly-loss gate (ARCH-H1): feed the realized 7-day PnL to the risk
        # engine so _check_weekly_loss is no longer a permanent no-op. Window
        # is measured by bar timestamps (not bar count) so it is correct for
        # any timeframe. The 7-day cutoff falls back to the oldest snapshot
        # when the session is younger than 7 days — a conservative (less
        # negative) measure during warmup.
        #
        # ISS-033: O(n) linear scan → O(1) amortized via a monotone forward
        # pointer. bar.timestamp is monotonically non-decreasing, so
        # week_ago_ms is too, and the first snapshot with ts >= week_ago_ms
        # only moves forward across bars. Eviction (pop(0)) shifts indices by
        # one, so the pointer is decremented to stay aligned to the same
        # snapshot; clamp at 0 to stay correct during warmup/empty history.
        self._equity_history.append((bar.timestamp, curr_equity))
        if len(self._equity_history) > self._equity_history_maxlen:
            self._equity_history.pop(0)
            if self._weekly_base_idx > 0:
                self._weekly_base_idx -= 1
        base_equity, self._weekly_base_idx, _ = _weekly_base_equity(
            self._equity_history, self._weekly_base_idx, bar.timestamp
        )
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
            # M4-5.9: release all pending reservations on kill switch.
            self._portfolio.release_all()
            await self._sink.send_alert(
                "KILL SWITCH ACTIVATED: drawdown breach",
                level="critical",
                extra={"drawdown": pf.current_drawdown},
            )
            self._running = False
            self._record_bar_latency(bar.symbol, started_at)
            return

        # Detect market regime for strategy gating (per symbol).
        # Two-layer design (ISS-20260720-001, resolved as design-property): regime
        # is a macro market-state gate (ADX strength via MarketRegimeDetector),
        # while strategy entries are micro signals (MA direction). They use
        # different detectors on purpose — a strategy's entries may fire on bars
        # the regime gate excludes, so backtest (generate_signals, no regime gate)
        # trades a superset of live/paper (on_bar, regime-gated). Live-faithful
        # validation uses paper-on_bar replay, not the vectorized backtest path.
        # Multi-symbol: a shared detector mixes OHLC across symbols and corrupts ADX.
        detector = self._regime_detectors.get(bar.symbol)
        if detector is None:
            detector = MarketRegimeDetector()
            self._regime_detectors[bar.symbol] = detector
        regime = detector.update(bar.high, bar.low, bar.close)

        # Collect signals from regime-eligible strategies, then consolidate per symbol.
        # M4-2.3: iterate per-(strategy, symbol) instances when available;
        # fall back to legacy (name, "") contexts for single-symbol callers.
        all_signals: list[Signal] = []
        for strategy in self._strategies:
            # Gate strategies by required regime
            if strategy.required_regime == "trending" and not regime.is_trending:
                continue
            if strategy.required_regime == "mean_reversion" and regime.is_trending:
                continue

            # Resolve the per-symbol instance and context (M4-2.2/2.3).
            key = (strategy.name, bar.symbol)
            instance = self._instances.get(key)
            if instance is None and not self._symbols:
                # Legacy path: no multi-symbol declaration; use the prototype
                # instance and the (name, "") context.
                instance = strategy
                key = (strategy.name, "")
            if instance is None:
                continue

            ctx = self._contexts.get(key)
            if not ctx:
                continue
            # T-s2-04: refresh the funding-feed freshness gate before on_bar so
            # stale/missing meta data fails closed on NEW entries only. No-op
            # when the feed is disabled (gate stays at its True default).
            self._apply_meta_freshness(strategy.name, bar.symbol, instance)
            # M4-4.3: offload strategy computation to a worker thread so CPU-heavy
            # strategies (Elliott Wave, ML ensemble) don't block the event loop
            # and starve other symbols' data fetch / signal processing.
            await asyncio.to_thread(instance.on_bar, ctx, bar)
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
        """Process a signal through risk check → position sizing → execution.

        M4-3.2: the entire risk-check → sizing → submit path is serialized
        under _signal_lock so concurrent signals (multi-symbol) cannot see
        stale portfolio snapshots between check and submit (TOCTOU layer 1).
        """
        async with self._signal_lock:
            await self._process_signal_inner(signal)

    async def _process_signal_inner(self, signal: Signal) -> None:
        """Inner signal processing (called under _signal_lock)."""
        started_at = perf_counter()
        portfolio = self._portfolio.portfolio
        # M4-5.4: pass pending snapshot so risk checks see in-flight exposure.
        pending = self._portfolio.pending_view()

        # FLAT signals close the existing position (reduce-only) rather than
        # opening a new short. Without this, a FLAT exit on a long would fall
        # through the `direction.value > 0` branch below and submit a SELL that
        # opens a brand-new short instead of flattening.
        if signal.direction == Direction.FLAT:
            await self._close_position_for_signal(signal)
            self._record_signal_latency(signal.strategy_id, started_at)
            return

        # T-s1-03 fail-closed gate: a restored-but-unverified session may only
        # close (FLAT handled above); new entries are refused until
        # reconciliation proves the restored book matches the exchange.
        if not self._recovery_verified:
            logger.warning("Signal blocked: recovery_unverified (%s)", signal.strategy_id)
            self._event_bus.publish(
                Event(
                    type=EVENT_RISK,
                    data={
                        "type": "signal_blocked",
                        "reason": "recovery_unverified",
                        "strategy_id": signal.strategy_id,
                    },
                )
            )
            self._record_signal_latency(signal.strategy_id, started_at)
            return

        # W21a: soft risk pauses (funding_risk_gate, …) block new entries only.
        if self._risk_pauses.is_paused:
            reasons = ",".join(sorted(self._risk_pauses.reasons))
            logger.warning(
                "Signal blocked: risk_pause (%s) strategy=%s",
                reasons,
                signal.strategy_id,
            )
            self._event_bus.publish(
                Event(
                    type=EVENT_RISK,
                    data={
                        "type": "signal_blocked",
                        "reason": f"risk_pause:{reasons}",
                        "strategy_id": signal.strategy_id,
                    },
                )
            )
            self._record_signal_latency(signal.strategy_id, started_at)
            return

        risk_decision = self._risk_engine.check(signal, portfolio, pending)

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
            await self._sink.send_alert(
                f"Signal blocked: {risk_decision.reason}",
                level="warning",
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

        # Observability: track signal via the sink (ISS-019).
        self._sink.record_signal(signal.strategy_id, str(signal.direction.value))

        # Position sizing (uses signal strength + per-strategy win rate).
        # ISS-038: allocation is passed INTO size() so the max_position_pct
        # cap clamps the final notional even when a compound strategy_id sums
        # to > 1 — the prior * allocation here re-inflated an already-capped
        # target past the cap.
        # Strategy × symbol weight when symbol-level RP is active; otherwise
        # identical to get_strategy_allocation (symbol weights empty).
        allocation = self._portfolio.get_allocation_for_signal(signal.strategy_id, signal.symbol)
        # KOL consensus as optional size reference only (never flips direction).
        # Default off: missing file / disabled config → multiplier 1.0.
        ref_mult = self._kol_reference_multiplier(signal)
        size = self._position_sizer.size(
            signal,
            portfolio,
            strategy_win_rates=self._strategy_win_rates,
            allocation=allocation,
            reference_multiplier=ref_mult,
        )

        if size <= 0:
            self._record_signal_latency(signal.strategy_id, started_at)
            return

        # Calculate quantity
        quantity = size / signal.price

        # Submit order
        side = OrderSide.BUY if signal.direction.value > 0 else OrderSide.SELL

        # M4-5.6: reserve pending exposure BEFORE submit so concurrent signals
        # (under the lock, or in-flight limit orders) see this exposure.
        import uuid

        local_order_id = str(uuid.uuid4())
        notional = size  # size is already in quote currency (notional)
        self._portfolio.reserve(local_order_id, signal.symbol, notional, signal.strategy_id)

        try:
            order = await self._execution.submit_order(
                OrderRequest(
                    symbol=signal.symbol,
                    side=side,
                    order_type="market",
                    quantity=quantity,
                    strategy_id=signal.strategy_id,
                )
            )
        except Exception:
            # Gateway exception: release the reservation immediately.
            self._portfolio.release(local_order_id)
            raise

        # M4-5.6: confirm/release based on fill result.
        if order.status == OrderStatus.FILLED:
            self._portfolio.confirm(local_order_id)
            # ISS-20260720-004 Wave 2: L4 fill update is owned by
            # ExecutionEngine.submit (single source, fee included). _process_signal
            # no longer re-updates L4 — that was the double-count path once L5
            # delegated to L4. Just refresh observability from the now-current L4.
            self._update_portfolio_observability()
        elif order.status == OrderStatus.PARTIAL:
            # M4-5.14: partial_confirm uses cumulative notional.
            cum_notional = order.filled_quantity * order.filled_price
            self._portfolio.partial_confirm(local_order_id, cum_notional)
        elif order.status == OrderStatus.REJECTED:
            self._portfolio.release(local_order_id)
        # else: SUBMITTED (limit order pending) — reservation stays until
        # fill callback or timeout releases it.

        self._record_signal_latency(signal.strategy_id, started_at)

    async def _close_position_for_signal(self, signal: Signal) -> None:
        """Flatten the existing position for a FLAT signal (reduce-only).

        Sizes the close order to the current held quantity so a FLAT exit
        flattens the position instead of opening a new short.
        """
        pos = self._portfolio.get_position(signal.symbol)
        if pos is None or abs(pos.quantity) < POSITION_EPSILON:
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
            # ISS-20260720-004 Wave 2: L4 fill update is owned by
            # ExecutionEngine.submit (reduce-only close included). Refresh
            # observability from the now-current L4 book.
            self._update_portfolio_observability()

    def _update_portfolio_observability(self) -> None:
        snapshot = self._portfolio.snapshot()
        self._sink.record_portfolio(
            total_value=float(snapshot["total_value"]),
            cash=float(snapshot["cash"]),
            drawdown=float(snapshot["drawdown"]),
            n_positions=int(snapshot["positions"]),
        )
        # s4 (T-s4-05): strategy-level PnL split. Positions carry strategy_id
        # (possibly compound "a,b"); attribute unrealized PnL to each
        # constituent and combine with realized PnL from cash deltas via the
        # portfolio's realized_pnl tracking. Best-effort — the sink swallows
        # failures, and zero-strategy positions are skipped.
        try:
            per_strategy: dict[str, float] = {}
            for pos in self._portfolio.positions.values():
                if pos.strategy_id:
                    constituents = strategy_id_constituents(pos.strategy_id) or [pos.strategy_id]
                    leg = (
                        pos.unrealized_pnl / len(constituents)
                        if constituents
                        else pos.unrealized_pnl
                    )
                    for c in constituents:
                        per_strategy[c] = per_strategy.get(c, 0.0) + leg
            for strategy_id, pnl in per_strategy.items():
                self._sink.record_strategy_pnl(strategy_id=strategy_id, pnl=float(pnl))
        except Exception:
            # Observability is best-effort — never break the trading loop.
            logger.warning("strategy_pnl observability push failed", exc_info=True)

    # --- T-s1-03: crash-recovery helpers ---

    def _restore_from_snapshot(self, snapshot: SessionSnapshot) -> None:
        """Restore L4 cash + positions from a checkpoint snapshot.

        Cash is restored as a delta against the freshly constructed portfolio
        (start() resets per-session state before this runs); positions
        overwrite via set_position (sync semantics — the checkpoint IS the
        authoritative record of the previous run's book). Open orders are NOT
        re-tracked: exchange-side state is re-established by reconciliation
        and the timeout/sweeper guards, never replayed blindly.
        """
        cash_delta = snapshot.cash - self._portfolio.cash
        if abs(cash_delta) > POSITION_EPSILON:
            self._portfolio.update_cash(cash_delta)
        for entry in snapshot.positions:
            symbol = str(entry.get("symbol", ""))
            if not symbol:
                continue
            self._portfolio.set_position(
                symbol,
                Position(
                    symbol=symbol,
                    quantity=float(entry.get("quantity", 0.0)),
                    entry_price=float(entry.get("entry_price", 0.0)),
                    current_price=float(entry.get("current_price", 0.0)),
                    unrealized_pnl=float(entry.get("unrealized_pnl", 0.0)),
                    strategy_id=str(entry.get("strategy_id", "")),
                ),
            )

    def _build_reconciliation_engine(self) -> None:
        """Construct the ReconciliationEngine from live session components."""
        gateway = self._execution.gateway
        if gateway is None:
            logger.warning("ReconciliationEngine not built — gateway unavailable")
            return
        self._reconciliation_engine = ReconciliationEngine(
            portfolio_manager=self._portfolio,
            gateway=gateway,
            order_manager=self._execution.order_manager,
            monitoring_sink=self._sink,
            drift_threshold_bps=self._config.reconciliation.drift_threshold_bps,
            order_staleness_threshold_seconds=(self._config.reconciliation.order_staleness_seconds),
        )

    async def _verify_recovery(self) -> bool:
        """Verify the restored book against the exchange (fail-closed).

        Returns True only when a reconciliation run completes with zero
        discrepancies; any error or drift keeps new-entry signals blocked.
        """
        self._build_reconciliation_engine()
        engine = self._reconciliation_engine
        if engine is None:
            return False
        try:
            report = await engine.run_daily_reconciliation()
        except Exception as e:
            logger.error("Recovery verification failed: %s", e)
            return False
        if report.status != "completed":
            logger.error("Recovery verification incomplete: %s", report.error_message)
            return False
        if report.discrepancies.total_discrepancies > 0:
            logger.critical(
                "Recovery verification found %d discrepancies — entries blocked",
                report.discrepancies.total_discrepancies,
            )
            return False
        return True

    def _build_snapshot(self) -> SessionSnapshot:
        """Snapshot the authoritative L4 state + in-flight orders."""
        positions = [
            {
                "symbol": p.symbol,
                "quantity": p.quantity,
                "entry_price": p.entry_price,
                "current_price": p.current_price,
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
        return SessionSnapshot(
            saved_at_ms=int(time.time() * 1000),
            mode=self._session_mode,
            cash=self._portfolio.cash,
            positions=positions,
            open_orders=open_orders,
            equity=self._portfolio.total_value,
        )

    async def _periodic_maintenance(self) -> None:
        """Time-based reconciliation + checkpoint save (called from data loop).

        Both duties are opt-in via YAML (reconciliation.enabled /
        state.enabled) and failure-isolated: a failed run never interrupts
        the data loop.
        """
        now = time.time()
        recon_cfg = self._config.reconciliation
        if (
            recon_cfg.enabled
            and self._reconciliation_engine is not None
            and now - self._last_reconciliation_at >= recon_cfg.interval_minutes * 60
        ):
            self._last_reconciliation_at = now
            try:
                await self._reconciliation_engine.run_daily_reconciliation()
            except Exception as e:
                logger.error("Periodic reconciliation failed: %s", e)
        state_cfg = self._config.state
        if (
            state_cfg.enabled
            and self._state_store is not None
            and now - self._last_checkpoint_at >= state_cfg.checkpoint_interval_minutes * 60
        ):
            self._last_checkpoint_at = now
            try:
                self._state_store.save_checkpoint(self._build_snapshot())
            except Exception as e:
                logger.error("Checkpoint save failed: %s", e)

    def _record_bar_latency(self, symbol: str, started_at: float) -> None:
        self._sink.record_bar_latency(symbol, perf_counter() - started_at)

    def _record_signal_latency(self, strategy_id: str, started_at: float) -> None:
        self._sink.record_signal_latency(strategy_id, perf_counter() - started_at)

    def _kol_reference_multiplier(self, signal: Signal) -> float:
        """Optional KOL consensus size scale (1.0 if disabled/unavailable).

        Never changes direction; fail-soft on any load/parse error.
        """
        try:
            from quantflow.strategy.kol_signals.reference_weight import (
                ReferenceWeightConfig,
                reference_multiplier,
            )

            kol_cfg = getattr(self._config, "kol_reference", None)
            if kol_cfg is None or not getattr(kol_cfg, "enabled", False):
                return 1.0
            rw = ReferenceWeightConfig(
                enabled=True,
                max_boost=float(getattr(kol_cfg, "max_boost", 0.15)),
                max_cut=float(getattr(kol_cfg, "max_cut", 0.25)),
                min_abs_score=float(getattr(kol_cfg, "min_abs_score", 0.35)),
                require_actionable=bool(getattr(kol_cfg, "require_actionable", True)),
                max_age_ms=int(float(getattr(kol_cfg, "max_age_hours", 6.0)) * 3600 * 1000),
            )
            path = str(
                getattr(
                    kol_cfg,
                    "consensus_path",
                    "data/kol_signals/latest_consensus.json",
                )
            )
            ref = reference_multiplier(
                signal.symbol,
                system_direction=signal.direction,
                consensus_path=path,
                config=rw,
            )
            return float(ref.multiplier)
        except Exception:
            return 1.0

    def _on_risk_event(self, event: Event) -> None:
        """Handle risk events — trigger kill switch on emergencies."""
        severity = event.data.get("severity", "warn")
        if severity == "emergency" and self._kill_switch and not self._kill_switch.is_active:
            logger.critical("Emergency risk event — will activate kill switch on next cycle")

    # ------------------------------------------------------------------ #
    # T-s2-04: funding-rate / open-interest meta feed.
    # Background collector round-robins symbols on the analyze-locked
    # cadence (funding >=60 s, OI >=30 s; MarketMetaFetcher's shared
    # RateLimiter keeps adjacent requests >=200 ms apart). Collector
    # failures are log-only — they MUST NOT interrupt the main data loop.
    # ------------------------------------------------------------------ #
    def _start_trades_ingest(self) -> None:
        """W23a: wire TradesIngestLoop when trades_poll_enabled."""
        from quantflow.data.trades_ingest import TradesIngestLoop, make_fetcher_adapter
        from quantflow.data.trades_store import TradesStore

        symbols = list(self._symbols or self._config.execution.symbols or [])
        if not symbols:
            logger.warning("trades poll enabled but no symbols resolved — ingest idle")
            return
        store_dir = str(
            getattr(self._config.execution, "trades_store_dir", "data/trades") or "data/trades"
        )
        interval = float(getattr(self._config.execution, "trades_poll_interval_s", 30.0) or 30.0)
        limit = int(getattr(self._config.execution, "trades_poll_limit", 100) or 100)
        self._trades_store = TradesStore(store_dir)
        # Prefer injectable fetcher (tests); else DataFetcher from config.
        fetcher = getattr(self, "_trades_fetcher", None)
        if fetcher is None:
            from quantflow.data.fetcher import DataFetcher

            fetcher = DataFetcher(self._config.data)
            self._trades_fetcher = fetcher

            async def _ensure_connect() -> None:
                with contextlib.suppress(Exception):
                    await fetcher.connect()

            asyncio.create_task(_ensure_connect())

        fetch_fn = make_fetcher_adapter(fetcher) if hasattr(fetcher, "fetch_trades") else fetcher
        self._trades_ingest = TradesIngestLoop(
            self._trades_store,
            fetch_trades=fetch_fn,
            symbols=symbols,
            interval_s=interval,
            limit=limit,
        )
        self._trades_ingest.start()
        logger.info(
            "Trades ingest started: symbols=%s interval=%.1fs dir=%s",
            symbols,
            interval,
            store_dir,
        )

    async def _bbo_poll_loop(self) -> None:
        """W20a: background ticker BBO poller (opt-in via bbo_poll_enabled).

        Fetches bid/ask via DataFetcher.fetch_ticker (or injectable
        ``_bbo_fetcher``) and pushes into the session BBO cache. Failures are
        log-only — never kill the main data loop. Default interval 5s.
        """
        from quantflow.data.fetcher import DataFetcher

        symbols = list(self._symbols or self._config.execution.symbols or [])
        if not symbols:
            logger.warning("bbo poll enabled but no symbols resolved — poll idle")
            return
        interval = max(
            1.0, float(getattr(self._config.execution, "bbo_poll_interval_s", 5.0) or 5.0)
        )
        fetcher = self._bbo_fetcher
        own_fetcher = False
        if fetcher is None:
            fetcher = DataFetcher(self._config.data)
            own_fetcher = True
            try:
                await fetcher.connect()
            except Exception as e:
                logger.error("BBO poll connect failed: %s", redact_secrets(str(e)))
        try:
            while self._running:
                for sym in symbols:
                    try:
                        ticker = await fetcher.fetch_ticker(sym)
                    except Exception as e:
                        logger.warning(
                            "BBO poll ticker failed (%s): %s",
                            sym,
                            redact_secrets(str(e)),
                        )
                        continue
                    bid = ticker.get("bid") if isinstance(ticker, dict) else None
                    ask = ticker.get("ask") if isinstance(ticker, dict) else None
                    if bid is None or ask is None:
                        # CCXT sometimes nests under info; tolerate missing
                        continue
                    self.push_ticker_bbo(sym, float(bid), float(ask))
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("BBO poll loop cancelled")
            raise
        finally:
            if own_fetcher and fetcher is not None:
                with contextlib.suppress(Exception):
                    await fetcher.disconnect()

    async def _meta_feed_loop(self) -> None:
        """Background funding/OI collector (opt-in via funding_feed_enabled)."""
        from quantflow.data.dq_monitor import DataQualityMonitor
        from quantflow.data.market_meta_fetcher import (
            FUNDING_POLL_INTERVAL_S,
            OI_POLL_INTERVAL_S,
            MarketMetaFetcher,
        )

        symbols = list(self._symbols or self._config.execution.symbols or [])
        if not symbols:
            logger.warning("funding feed enabled but no symbols resolved — feed idle")
            return
        if self._meta_fetcher is None:
            self._meta_fetcher = MarketMetaFetcher(self._config.data)
        if self._dq_monitor is None:
            self._dq_monitor = DataQualityMonitor(
                enable_prometheus=False, monitoring_sink=self._sink
            )
        fetcher = self._meta_fetcher
        try:
            await fetcher.connect()
        except Exception as e:
            # Connection failure must not kill the feed — per-cycle fetch
            # errors below are isolated and the loop keeps retrying.
            logger.error("Meta feed connect failed: %s", redact_secrets(str(e)))

        next_funding_at = 0.0
        next_oi_at = 0.0
        try:
            while self._running:
                now = time.monotonic()
                try:
                    if now >= next_funding_at:
                        await self._meta_poll_funding(symbols)
                        next_funding_at = time.monotonic() + FUNDING_POLL_INTERVAL_S
                    if now >= next_oi_at:
                        await self._meta_poll_oi(symbols)
                        next_oi_at = time.monotonic() + OI_POLL_INTERVAL_S
                except Exception as e:
                    logger.warning("Meta feed cycle error: %s", redact_secrets(str(e)))
                await asyncio.sleep(_META_FEED_SLEEP_S)
        except asyncio.CancelledError:
            logger.info("Meta feed loop cancelled")
            raise

    async def _meta_poll_funding(self, symbols: list[str]) -> None:
        """One funding-rate round over all symbols (per-symbol isolation)."""
        fetcher = self._meta_fetcher
        dq_monitor = self._dq_monitor
        if fetcher is None or dq_monitor is None:
            return
        for sym in symbols:
            try:
                snap = await fetcher.fetch_funding_rate(sym)
            except Exception as e:
                logger.warning(
                    "Meta feed funding fetch failed (%s): %s", sym, redact_secrets(str(e))
                )
                continue
            # dq freshness validation (stale_funding on age > 2x settlement).
            dq = dq_monitor.validate_funding_rate(
                {
                    "symbol": sym,
                    "fetched_at_ms": snap.fetched_at_ms,
                    "settled_interval_ms": snap.settlement_interval_ms,
                }
            )
            if not dq.valid:
                await self._sink.send_alert(
                    f"Funding feed stale for {sym} — entries gated (fail-closed)",
                    level="warning",
                    extra={"violations": dq.violations},
                )
            instance = self._instances.get(("funding_rate", sym))
            if instance is not None and hasattr(instance, "update_funding_rate"):
                instance.update_funding_rate(snap.funding_rate)
            meta = self._meta_fresh.setdefault(
                sym, {"funding": False, "oi": False, "settled_interval_ms": 0}
            )
            meta["funding"] = True
            meta["funding_at_ms"] = snap.fetched_at_ms
            meta["settled_interval_ms"] = snap.settlement_interval_ms
            self._last_funding_rate[sym] = float(snap.funding_rate)
            # W21a: funding risk gate (opt-in) — soft pause or kill
            self._apply_funding_risk_gate(sym, float(snap.funding_rate))
            self._event_bus.publish(
                Event(
                    type=EVENT_FUNDING,
                    data={
                        "symbol": sym,
                        "funding_rate": snap.funding_rate,
                        "fetched_at_ms": snap.fetched_at_ms,
                        "settled_interval_ms": snap.settlement_interval_ms,
                    },
                )
            )

    def _apply_funding_risk_gate(self, symbol: str, funding_rate: float) -> None:
        """W21a: opt-in funding absolute-rate risk gate (not alpha).

        Soft path: add/remove pause reason ``funding_risk_gate`` on session
        ``_risk_pauses`` (blocks new entries only). Hard path (config
        ``funding_risk_gate_kill``): schedule KillSwitch.activate.
        Default config leaves the gate disabled → no-op.
        """
        from quantflow.signal.funding_risk_gate import REASON, evaluate_funding_risk

        risk = self._config.risk
        decision = evaluate_funding_risk(
            funding_rate,
            enabled=bool(getattr(risk, "funding_risk_gate_enabled", False)),
            max_abs=float(getattr(risk, "max_funding_rate_abs", 0.001) or 0.001),
            symbol=symbol,
        )
        if not bool(getattr(risk, "funding_risk_gate_enabled", False)):
            return
        if decision.blocked:
            self._risk_pauses.add(REASON)
            logger.warning(
                "Funding risk gate blocked new entries: %s (%s)",
                decision.reason,
                symbol,
            )
            self._event_bus.publish(
                Event(
                    type=EVENT_RISK,
                    data={
                        "type": "funding_risk_gate",
                        "symbol": symbol,
                        **decision.to_dict(),
                    },
                )
            )
            if bool(getattr(risk, "funding_risk_gate_kill", False)) and self._kill_switch:
                if not self._kill_switch.is_active:
                    # Fire-and-forget hard stop; failures logged by KillSwitch.
                    asyncio.create_task(self._kill_switch.activate(decision.reason or REASON))
        else:
            self._risk_pauses.remove(REASON)

    def note_funding_rate(self, symbol: str, funding_rate: float) -> None:
        """Public helper for tests / injectors to feed funding into the risk gate."""
        self._last_funding_rate[symbol] = float(funding_rate)
        self._apply_funding_risk_gate(symbol, float(funding_rate))

    async def _meta_poll_oi(self, symbols: list[str]) -> None:
        """One open-interest round over all symbols (per-symbol isolation)."""
        fetcher = self._meta_fetcher
        dq_monitor = self._dq_monitor
        if fetcher is None or dq_monitor is None:
            return
        for sym in symbols:
            try:
                snap = await fetcher.fetch_open_interest(sym)
            except Exception as e:
                logger.warning("Meta feed OI fetch failed (%s): %s", sym, redact_secrets(str(e)))
                continue
            dq = dq_monitor.validate_open_interest(
                {"symbol": sym, "fetched_at_ms": snap.fetched_at_ms}
            )
            if not dq.valid:
                await self._sink.send_alert(
                    f"OI feed stale for {sym} — entries gated (fail-closed)",
                    level="warning",
                    extra={"violations": dq.violations},
                )
            instance = self._instances.get(("funding_rate", sym))
            if instance is not None and hasattr(instance, "update_open_interest"):
                instance.update_open_interest(snap.open_interest)
            meta = self._meta_fresh.setdefault(
                sym, {"funding": False, "oi": False, "settled_interval_ms": 0}
            )
            meta["oi"] = True
            meta["oi_at_ms"] = snap.fetched_at_ms
            self._event_bus.publish(
                Event(
                    type=EVENT_OI,
                    data={
                        "symbol": sym,
                        "open_interest": snap.open_interest,
                        "fetched_at_ms": snap.fetched_at_ms,
                    },
                )
            )

    def _meta_data_fresh(self, symbol: str) -> bool:
        """Fail-closed freshness check for a symbol's funding/OI feed.

        False (entries blocked) when the feed never produced data, or when
        funding age > 2 x settlement interval, or OI age > 600 s — the same
        thresholds dq_monitor enforces (analyze F4 / locked constants).
        """
        meta = self._meta_fresh.get(symbol)
        if not meta or not meta.get("funding") or not meta.get("oi"):
            return False
        now_ms = time.time() * 1000.0
        interval_ms = float(meta.get("settled_interval_ms") or 0)
        funding_at = meta.get("funding_at_ms")
        oi_at = meta.get("oi_at_ms")
        if interval_ms <= 0 or funding_at is None or oi_at is None:
            return False
        if now_ms - float(funding_at) > 2 * interval_ms:
            return False
        return now_ms - float(oi_at) <= 600_000.0

    def _apply_meta_freshness(self, strategy_name: str, symbol: str, instance: Any) -> None:
        """Push the current feed-freshness state into a strategy instance."""
        if not self._config.execution.funding_feed_enabled:
            return
        if strategy_name != "funding_rate":
            return
        setter = getattr(instance, "set_freshness_gate", None)
        if setter is None:
            return
        setter(self._meta_data_fresh(symbol))

    async def run_data_loop(
        self,
        symbol: str = "",
        timeframe: str = "1h",
        interval_seconds: int = 60,
        symbols: list[str] | None = None,
    ) -> None:
        """Continuously fetch new bars and feed them into on_bar().

        This is the main loop for paper/live mode.

        M4-4.1/4.2: supports multi-symbol via a single poller that rotates
        over all symbols each interval. A single shared DataFetcher (and thus
        a single CCXT exchange instance) is used for all symbols to ensure
        the rate-limit throttler coordinates globally (M4-1.2 invariant).

        Args:
            symbol: Legacy single-symbol argument (backward compat).
            timeframe: Candle interval.
            interval_seconds: Seconds between poll cycles.
            symbols: Multi-symbol list. If provided, overrides ``symbol``.
                If both are empty, falls back to config.execution.symbols.
        """
        from quantflow.data.fetcher import DataFetcher
        from quantflow.data.store import DataStore

        # Resolve the symbol list (M4-4.1): explicit arg > config > legacy single.
        resolved_symbols = symbols or self._config.execution.symbols or []
        if not resolved_symbols and symbol:
            resolved_symbols = [symbol]
        if not resolved_symbols:
            raise ValueError(
                "No symbols provided: pass symbol=, symbols=, or set execution.symbols in config."
            )

        if self._config.execution.mode == "paper":
            # Paper mode: replay local parquet for the first symbol (legacy
            # behavior). Multi-symbol paper replay uses the live fetcher path
            # below with local data (future: per-symbol parquet replay).
            first_symbol = resolved_symbols[0]
            store = DataStore(self._config.data.parquet_dir, ":memory:")
            timeframe_filter: str | None = timeframe
            pending_frame = store.query(first_symbol, timeframe=timeframe_filter)
            if pending_frame.empty:
                # Timeframe fallback: the requested timeframe is not in local
                # parquet. Rather than silently trading a different timeframe
                # than configured (a backtest/live parity leak — ARCH-M6), log
                # at WARNING and replay whatever IS available so the operator
                # sees the divergence. The log names both the requested and the
                # fallback cadence explicitly.
                pending_frame = store.query(first_symbol)
                if not pending_frame.empty:
                    timeframe_filter = None
                    logger.warning(
                        "Paper session requested %s/%s but only alternate local "
                        "parquet data exists; replaying available bars (timeframe "
                        "divergence from config — verify this is intended).",
                        first_symbol,
                        timeframe,
                    )
            try:
                if not pending_frame.empty:
                    await self._run_local_data_loop(
                        store=store,
                        symbol=first_symbol,
                        interval_seconds=interval_seconds,
                        pending_frame=pending_frame,
                        timeframe_filter=timeframe_filter,
                    )
                    return
            finally:
                store.close()

        fetcher = DataFetcher(self._config.data)
        # M4-4.2: per-symbol last_timestamp tracking for the rotation poller.
        last_timestamps: dict[str, int | None] = {s: None for s in resolved_symbols}
        connected = False

        try:
            while self._running:
                if not connected:
                    try:
                        await fetcher.connect()
                        connected = True
                        self._last_error = None
                    except Exception as e:
                        self._last_error = f"Data feed connection error: {redact_secrets(str(e))}"
                        logger.error("%s", self._last_error)
                        await fetcher.disconnect()
                        self.check_health()
                        self._execution.check_timeouts()
                        await asyncio.sleep(interval_seconds)
                        continue

                # M4-4.2: single poller rotates over all symbols each cycle.
                # The shared fetcher's CCXT throttler coordinates rate limits
                # globally across all symbols (M4-1.2 invariant).
                for sym in resolved_symbols:
                    try:
                        df = await fetcher.fetch_ohlcv(
                            sym,
                            timeframe,
                            start=None,
                            limit=10,
                        )
                        self._last_error = None

                        if not df.empty and "timestamp" in df.columns:
                            for row in df.itertuples(index=False):
                                ts = int(row.timestamp)
                                prev_ts = last_timestamps[sym]
                                if prev_ts is None or ts > prev_ts:
                                    bar = Bar(
                                        symbol=sym,
                                        timestamp=ts,
                                        open=float(row.open),
                                        high=float(row.high),
                                        low=float(row.low),
                                        close=float(row.close),
                                        volume=float(row.volume),
                                    )
                                    await self.on_bar(bar)
                                    last_timestamps[sym] = ts

                    except Exception as e:
                        self._last_error = f"Data feed error ({sym}): {redact_secrets(str(e))}"
                        logger.error("%s", self._last_error)
                        # Per-symbol error does not disconnect the shared fetcher;
                        # other symbols may still succeed. Only a connection-level
                        # failure (handled below) triggers disconnect.

                # Health check
                self.check_health()

                # T-s1-03: periodic reconciliation + checkpoint (both opt-in).
                await self._periodic_maintenance()

                # Order timeout check — cancel timed-out orders on the exchange
                # (odyssey-improve REL-H4): previously the returned ids were
                # discarded, so an exchange-still-open order could fill later
                # against a locally-dead id with no position update.
                # M4-5.7/5.11: quadrant decision matrix for pending release.
                for oid, sym in self._execution.check_timeouts():
                    if not sym:
                        self._portfolio.release(oid)
                        continue
                    cancel_ok = False
                    try:
                        cancel_ok = await self._execution.cancel(oid, sym)
                    except Exception as exc:
                        logger.warning("Timeout cancel failed for %s: %s", oid, exc)
                    sync_ok = False
                    with contextlib.suppress(Exception):
                        sync_ok = await self._execution.sync_positions()
                    # Quadrant A/B/C: at least one source confirmed state.
                    if cancel_ok or sync_ok:
                        self._portfolio.release(oid)
                    else:
                        # Quadrant D: completely blind — hold pending (Fail-Closed).
                        logger.critical(
                            "Timeout: cancel AND sync both failed for %s (%s) — "
                            "pending HELD (stale sweeper will resolve)",
                            oid,
                            sym,
                        )

                # M4-5.12/5.13: sweep stale pending entries (last-resort guard).
                stale = self._portfolio.sweep_stale_pending(max_age_ms=120_000)
                if stale:
                    await self._sink.send_alert(
                        f"Swept {len(stale)} stale pending entries — manual position review needed",
                        level="critical",
                    )

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
                    self._last_error = f"Local data replay error: {redact_secrets(str(e))}"
                    logger.error("%s", self._last_error)

                self.check_health()
                # T-s1-03: periodic reconciliation + checkpoint (both opt-in).
                await self._periodic_maintenance()
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
        # T-s2-04: drain the meta feed task so stop() leaves no orphan loop.
        if self._meta_feed_task is not None and not self._meta_feed_task.done():
            self._meta_feed_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._meta_feed_task
        # W20a: drain BBO poll task
        if self._bbo_poll_task is not None and not self._bbo_poll_task.done():
            self._bbo_poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._bbo_poll_task
            self._bbo_poll_task = None
        # W23a: drain trades ingest
        if self._trades_ingest is not None:
            with contextlib.suppress(Exception):
                await self._trades_ingest.stop()
            self._trades_ingest = None
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
    def event_bus(self) -> EventBus:
        """ISS-20260723-017: public accessor for the session's EventBus.

        Previously the web facade (SessionManager) read ``session._event_bus``
        via ``getattr`` — a private-attribute poke that violates the facade
        contract and silently returns None (the default) if the attribute is
        ever renamed. Exposing it as a property gives a stable public seam.
        """
        return self._event_bus

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
        result = await self._kill_switch.activate(reason)
        # M4-5.9: release all pending reservations on manual kill switch.
        self._portfolio.release_all()
        return result

    def adjust_capital(self, capital: float) -> None:
        """Set the portfolio capital atomically (initial capital + peak)."""
        cash_delta = capital - self._portfolio.cash
        if abs(cash_delta) > POSITION_EPSILON:
            self._portfolio.update_cash(cash_delta)
        self._portfolio.set_capital_baseline(capital)
