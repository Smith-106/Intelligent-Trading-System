"""Paper historical replay — production-path simulation on real data (C1).

Replay local parquet bars through ``TradingSession.on_bar`` in paper mode —
the same event path as live — collecting fills, risk events and a per-bar
equity curve into a report. Unlike ``BacktestEngine`` (a separate vectorized
engine that never exercises RiskEngine/PositionSizer/PaperGateway), this
drives the real production wiring (ISS-20260803-002/003 seams included).

Harness pitfalls pinned here (both were silent-zero regressions):

- M4 (multi-symbol) re-keyed legacy contexts to ``(name, "")`` — a bare
  ``name`` key is never found by ``on_bar`` and every strategy is gated out
  with zero signals, no error.
- ``start()`` normally rebinds the L5 PositionManager to the shared L4
  portfolio via ``set_portfolio``; bypassing ``start()`` leaves fills landing
  on a private default book and the session equity never moves.

Known signal-density caveat: trend_following gates on
``required_regime="trending"`` (ADX>=25) — on real BTC/USDT 1h only a few bars
per month qualify; mean_reversion trades non-trending bars and yields a denser
book (p1-live-verification-checklist-018).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import pandas as pd

from quantflow.common.config import AppConfig
from quantflow.common.event_bus import EVENT_FILL, EVENT_RISK
from quantflow.common.models import Bar
from quantflow.common.monitoring_sink import NullMonitoringSink
from quantflow.execution.engine import ExecutionEngine
from quantflow.execution.paper_gateway import PaperGateway
from quantflow.strategy.base import StrategyBase, StrategyContext
from quantflow.strategy.engine import TradingSession
from quantflow.strategy.templates.funding_rate import FundingRateStrategy
from quantflow.strategy.templates.mean_reversion import MeanReversionStrategy
from quantflow.strategy.templates.non_ma_signal import NonMaSignalStrategy
from quantflow.strategy.templates.trend_following import TrendFollowingStrategy
from quantflow.strategy.templates.volatility_breakout import VolatilityBreakoutStrategy

STRATEGIES = {
    "trend_following": TrendFollowingStrategy,
    "mean_reversion": MeanReversionStrategy,
    "volatility_breakout": VolatilityBreakoutStrategy,
    "non_ma_signal": NonMaSignalStrategy,
    "funding_rate": FundingRateStrategy,
}


def _resolve_strategy_class(strategy_name: str) -> type[StrategyBase]:
    """Resolve catalog + research-only strategies (W21b: liu_yudong_wave)."""
    if strategy_name in STRATEGIES:
        return STRATEGIES[strategy_name]
    if strategy_name in ("liu_yudong_wave", "elliott_wave_liu"):
        from quantflow.strategy.elliott_wave_strategy import LiuYudongWaveStrategy

        return LiuYudongWaveStrategy  # type: ignore[return-value]
    raise ValueError(
        f"Unknown strategy '{strategy_name}'. Available: {[*list(STRATEGIES), 'liu_yudong_wave']}"
    )


BARS_PER_YEAR = 24 * 365  # 1h bars (back-compat default)

# Minutes per bar for annualization and HTF nesting.
_TF_MINUTES: dict[str, int] = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "6h": 360,
    "12h": 720,
    "1d": 1440,
    "1w": 10080,
}

# Entry TF → higher-timeframe gate (A/a nested). Prefer ~4× entry when OKX-native.
NESTED_HTF_MAP: dict[str, str] = {
    "5m": "1h",
    "15m": "1h",
    "30m": "2h",
    "1h": "4h",
    "2h": "12h",
    "4h": "1d",
    "6h": "1d",
    "12h": "1d",
    "1d": "1w",
}


def bars_per_year(timeframe: str = "1h") -> float:
    """Bars per year for Sharpe annualization on the given bar interval."""
    minutes = _TF_MINUTES.get(timeframe)
    if minutes is None:
        return float(BARS_PER_YEAR)
    return float((365 * 24 * 60) / minutes)


def nested_htf_for(entry_tf: str = "1h") -> str:
    """Higher timeframe used by the nested direction gate for ``entry_tf``."""
    return NESTED_HTF_MAP.get(entry_tf, "4h")


class RecordingSink(NullMonitoringSink):
    """Sink that records every alert so the report shows risk hits."""

    def __init__(self) -> None:
        super().__init__()
        self.alerts: list[dict[str, object]] = []

    async def send_alert(
        self,
        message: str,
        level: str = "warning",
        extra: dict[str, object] | None = None,
    ) -> dict[str, bool]:
        self.alerts.append({"message": message, "level": level, "extra": extra or {}})
        return {}


def build_session(
    strategy_name: str,
    capital: float = 100_000.0,
    sink: RecordingSink | None = None,
    config: AppConfig | None = None,
    params: dict[str, Any] | None = None,
    research_risk_bypass: bool = True,
) -> TradingSession:
    """Build a paper TradingSession with PaperGateway injected directly,
    bypassing start()'s Prometheus/network init and live data loop.

    The session's ExecutionEngine is rebuilt with the gateway bound at
    construction (OrderRouter binds in __init__; bypassing start() skips
    set_gateway) and the A2 (ISS-20260803-003) seams threaded through: the
    exchange health monitor + shared sink stay attached.

    ``research_risk_bypass`` (default True) preserves the historical research
    path: kill switch off and a very loose max_drawdown so long multi-year
    replays are not truncated. Set False to honour ``config.risk`` for
    production-fidelity ablation studies. Fee/slippage always come from
    ``config.execution`` (defaults match AppConfig).
    """
    cfg = config or AppConfig()
    cfg.execution.mode = "paper"
    if research_risk_bypass:
        # Controlled research simulation — no kill switch / loose DD trip.
        cfg.risk.kill_switch_enabled = False
        cfg.risk.max_drawdown = -0.90

    strategy_cls = _resolve_strategy_class(strategy_name)
    strategy = strategy_cls(params=params)  # type: ignore[abstract]
    session = TradingSession(cfg, [strategy], monitoring_sink=sink)
    session._execution = ExecutionEngine(
        event_bus=session._event_bus,
        gateway=PaperGateway(
            {
                "initial_capital": capital,
                "taker_fee": cfg.execution.taker_fee,
                "maker_fee": cfg.execution.maker_fee,
                "slippage": cfg.execution.slippage,
            }
        ),
        timeout=cfg.execution.order_timeout,
        monitoring_sink=sink,
        health_monitor=session._exchange_health,
    )
    # Rebind the L5 PositionManager to the session's shared L4 portfolio —
    # start() normally does this; without it fills update a private default
    # book and session._portfolio (read by on_bar/equity) never moves.
    session._execution.set_portfolio(session._portfolio)
    # start() sets a uniform per-strategy allocation; since we bypass start(),
    # replicate it here (ISS-20260720-002: without it every signal is dropped
    # at size <= 0 and the replay produces zero orders).
    session._portfolio.set_allocation(
        {s.name: 1.0 / len(session._strategies) for s in session._strategies}
    )
    return session


def build_multi_symbol_session(
    strategy_name: str,
    symbols: list[str],
    capital: float = 100_000.0,
    sink: RecordingSink | None = None,
    config: AppConfig | None = None,
    params: dict[str, Any] | None = None,
    research_risk_bypass: bool = True,
    max_position_pct: float | None = None,
    max_positions: int | None = None,
) -> TradingSession:
    """Paper session with per-symbol strategy clones (shared book).

    Mirrors ``TradingSession.start(symbols=...)`` instance wiring without the
    live data loop / Prometheus init. ``max_position_pct`` / ``max_positions``
    override RiskConfig when provided (shared-cap experiments).
    """
    if not symbols:
        raise ValueError("symbols must be non-empty")

    cfg = config or AppConfig()
    cfg.execution.mode = "paper"
    if research_risk_bypass:
        cfg.risk.kill_switch_enabled = False
        cfg.risk.max_drawdown = -0.90
    if max_position_pct is not None:
        cfg.risk.position_limit_pct = float(max_position_pct)
    if max_positions is not None:
        cfg.risk.max_positions = int(max_positions)

    strategy_cls = _resolve_strategy_class(strategy_name)
    strategy = strategy_cls(params=params)  # type: ignore[abstract]
    session = TradingSession(cfg, [strategy], monitoring_sink=sink)
    session._execution = ExecutionEngine(
        event_bus=session._event_bus,
        gateway=PaperGateway(
            {
                "initial_capital": capital,
                "taker_fee": cfg.execution.taker_fee,
                "maker_fee": cfg.execution.maker_fee,
                "slippage": cfg.execution.slippage,
            }
        ),
        timeout=cfg.execution.order_timeout,
        monitoring_sink=sink,
        health_monitor=session._exchange_health,
    )
    session._execution.set_portfolio(session._portfolio)
    session._portfolio.set_allocation(
        {s.name: 1.0 / len(session._strategies) for s in session._strategies}
    )

    # Wire multi-symbol instances the same way start(symbols=...) does.
    from quantflow.strategy.factory import create_all_per_symbol

    session._symbols = list(symbols)
    session._instances = create_all_per_symbol(session._strategies, session._symbols)
    session._contexts = {}
    session._running = False

    # Shared-book symbol-level RP: seed equal symbol weights so early signals
    # are not full-sized before the first rebalance tick.
    po = cfg.risk.portfolio_optimization
    if po.enabled and po.level == "symbol" and symbols:
        n = len(symbols)
        session._portfolio.set_symbol_allocation({sym: 1.0 / n for sym in symbols})
    return session


async def replay_multi(
    session: TradingSession,
    bars_by_symbol: dict[str, pd.DataFrame],
    fills: list[dict[str, object]] | None = None,
    risk_events: list[dict[str, object]] | None = None,
    direction_gate: bool | str = False,
    entry_tf: str = "1h",
) -> list[dict[str, float]]:
    """Replay multiple symbols on a shared session (timestamp-aligned).

    At each unique timestamp, symbols present on that bar are fed to
    ``on_bar`` in deterministic symbol order. Equity is sampled once per
    timestamp after all symbols for that tick have been processed.
    """
    fills = fills if fills is not None else []
    risk_events = risk_events if risk_events is not None else []

    if not bars_by_symbol:
        raise ValueError("bars_by_symbol is empty")

    # Optional direction gate: wrap each per-symbol instance with its own allow.
    if direction_gate:
        gate_name = direction_gate if isinstance(direction_gate, str) else "sma"
        builders = _gate_builders(entry_tf)
        if gate_name not in builders:
            raise ValueError(f"Unknown gate '{gate_name}'. Available: {list(builders)}")
        for symbol, df in bars_by_symbol.items():
            allow = builders[gate_name](df)
            for key, inst in list(session._instances.items()):
                if key[1] == symbol:
                    session._instances[key] = _DirectionGateWrapper(inst, allow)

    session._running = True
    # Init contexts for multi-symbol instances (and prototypes for allocation keys).
    for (name, symbol), instance in session._instances.items():
        ctx = StrategyContext()
        instance.on_init(ctx)
        session._contexts[(name, symbol)] = ctx
    for strategy in session._strategies:
        if (strategy.name, "") not in session._contexts:
            ctx = StrategyContext()
            strategy.on_init(ctx)
            session._contexts[(strategy.name, "")] = ctx

    session.event_bus.subscribe(EVENT_FILL, lambda e: fills.append(dict(e.data)))
    session.event_bus.subscribe(EVENT_RISK, lambda e: risk_events.append(dict(e.data)))

    # Build per-timestamp bar map: ts -> list[(symbol, row)]
    by_ts: dict[int, list[tuple[str, Any]]] = {}
    for symbol, df in bars_by_symbol.items():
        for row in df.itertuples(index=False):
            ts = int(row.timestamp)
            by_ts.setdefault(ts, []).append((symbol, row))

    curve: list[dict[str, float]] = []
    for ts in sorted(by_ts):
        rows = sorted(by_ts[ts], key=lambda x: x[0])  # stable symbol order
        for symbol, row in rows:
            bar = Bar(
                symbol=symbol,
                timestamp=ts,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
            )
            await session.on_bar(bar)
        curve.append(
            {
                "timestamp": ts,
                "equity": round(session._portfolio.total_value, 4),
            }
        )
    return curve


async def replay(
    session: TradingSession,
    bars_df: pd.DataFrame,
    symbol: str,
    fills: list[dict[str, object]] | None = None,
    risk_events: list[dict[str, object]] | None = None,
    direction_gate: bool | str = False,
    gate_sma_period: int = 200,
    entry_tf: str = "1h",
    bar_hook: Callable[[TradingSession, Any], None] | None = None,
) -> list[dict[str, float]]:
    """Feed each bar through on_bar; return the per-bar equity curve.

    ``fills`` / ``risk_events`` are appended to in place (caller-owned) so the
    caller can inspect the raw event streams alongside the curve.

    ``direction_gate`` (A/B research switch, default off = byte-for-byte):
    wraps the strategy so it does NOT emit signals while ``close`` is below its
    simple moving average (SMA period ``gate_sma_period``) — i.e. mean-reversion
    stops catching falling knives in bear regimes. The gate is evaluated on the
    bar that precedes the strategy's on_bar (same bar), and is inactive while
    the SMA is undefined (warm-up window).
    """
    fills = fills if fills is not None else []
    risk_events = risk_events if risk_events is not None else []

    if direction_gate:
        gate_name = direction_gate if isinstance(direction_gate, str) else "sma"
        builders = _gate_builders(entry_tf)
        if gate_name == "sma" and gate_sma_period != 200:
            allow = _sma_allow(bars_df, gate_sma_period)
        elif gate_name not in builders:
            raise ValueError(f"Unknown gate '{gate_name}'. Available: {list(builders)}")
        else:
            allow = builders[gate_name](bars_df)
        session._strategies[0] = _DirectionGateWrapper(session._strategies[0], allow)

    session._running = True
    for strategy in session._strategies:
        ctx = StrategyContext()
        strategy.on_init(ctx)
        # M4: legacy single-symbol contexts are keyed by (name, "") — a bare
        # name key is never found by on_bar, silently gating every strategy
        # out (regression guard: test_paper_replay harness).
        session._contexts[(strategy.name, "")] = ctx

    session.event_bus.subscribe(EVENT_FILL, lambda e: fills.append(dict(e.data)))
    session.event_bus.subscribe(EVENT_RISK, lambda e: risk_events.append(dict(e.data)))

    curve: list[dict[str, float]] = []
    for row in bars_df.itertuples(index=False):
        bar = Bar(
            symbol=symbol,
            timestamp=int(row.timestamp),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
        if bar_hook is not None:
            bar_hook(session, row)
        await session.on_bar(bar)
        curve.append(
            {
                "timestamp": int(row.timestamp),
                "equity": round(session._portfolio.total_value, 4),
            }
        )
    return curve


class _DirectionGateWrapper(StrategyBase):
    """Strategy decorator: suppress signal emission while the direction gate
    is closed.

    A/B research switch for the direction-gate experiment (bear-regime
    mean-reversion protection). ``allow`` is a precomputed per-bar boolean
    Series (True = gate open); the wrapper suppresses emission while False.
    Keeps the inner strategy's state updates untouched; only emission is
    suppressed.
    """

    def __init__(self, inner: StrategyBase, allow: pd.Series) -> None:
        super().__init__(name=inner.name)
        self._inner = inner
        self._allow = allow
        self._idx = 0
        # Preserve regime gating: the engine skips strategies whose
        # required_regime mismatches the detected regime; a wrapper that
        # resets this to "any" would bypass the gate and trade trending
        # bars the inner strategy is supposed to sit out.
        self.required_regime = inner.required_regime

    def on_init(self, ctx: StrategyContext) -> None:
        self._inner.on_init(ctx)

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        allow = self._allow.iloc[self._idx] if self._idx < len(self._allow) else True
        self._idx += 1
        if not bool(allow):
            return  # gate closed: suppress mean-reversion entries
        self._inner.on_bar(ctx, bar)

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        return self._inner.generate_signals(df)


def _sma_allow(df: pd.DataFrame, period: int) -> pd.Series:
    """Gate: close >= SMA(period). NaN warm-up rows are open (True)."""
    sma = df["close"].rolling(period).mean()
    return df["close"].fillna(0) >= sma.fillna(float("-inf"))


def _ema_allow(df: pd.DataFrame, period: int) -> pd.Series:
    """Gate: close >= EMA(period) — faster response than SMA."""
    ema = df["close"].ewm(span=period, adjust=False).mean()
    return df["close"] >= ema


def _slope_allow(df: pd.DataFrame, period: int) -> pd.Series:
    """Gate AA: close >= SMA(period) AND SMA rising (slope >= 0).

    Two same-family confirmations (price above + average trending up) —
    blocks entries during the early leg of a bear move before price has
    crossed below the average.
    """
    sma = df["close"].rolling(period).mean()
    rising = sma.diff().fillna(0.0) >= 0.0
    above = df["close"].fillna(0) >= sma.fillna(float("-inf"))
    return above & rising


def _dual_ema_allow(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> pd.Series:
    """Gate AB: golden-cross regime — fast EMA above slow EMA.

    Mixed family (two EMAs, crossing state) — trend must be established
    (fast > slow) before mean-reversion entries are allowed.
    """
    fast_ema = df["close"].ewm(span=fast, adjust=False).mean()
    slow_ema = df["close"].ewm(span=slow, adjust=False).mean()
    return fast_ema >= slow_ema


def _nested_allow(
    df: pd.DataFrame,
    htf_agg: str = "4h",
    period: int = 50,
    entry_tf: str = "1h",
) -> pd.Series:
    """Gate A/a: higher-timeframe direction gate over lower-timeframe entries.

    Aggregates entry bars into ``htf_agg`` buckets, computes SMA(period) on
    the HTF close, and opens the gate only while the *previous completed* HTF
    bar's close is >= its SMA — the HTF value is visible to the LTF only
    after the HTF bar closes (no look-ahead; M3-P0 constraint).
    """
    close = df["close"]
    entry_min = _TF_MINUTES.get(entry_tf, 60)
    htf_min = _TF_MINUTES.get(htf_agg, entry_min * 4)
    htf_bars = max(1, htf_min // entry_min)
    htf_close = close.groupby(close.index // htf_bars).transform("last")
    htf_sma = htf_close.rolling(period * htf_bars).mean()
    # Previous bucket's value (shift by one bucket = htf_bars rows).
    prev_htf_close = htf_close.shift(htf_bars)
    prev_htf_sma = htf_sma.shift(htf_bars)
    return prev_htf_close.fillna(0) >= prev_htf_sma.fillna(float("-inf"))


def _gate_builders(entry_tf: str = "1h") -> dict[str, Callable[[pd.DataFrame], pd.Series]]:
    """Gate factory parameterized by the entry bar timeframe."""
    htf = nested_htf_for(entry_tf)

    def _sma(df: pd.DataFrame) -> pd.Series:
        return _sma_allow(df, 200)

    def _ema(df: pd.DataFrame) -> pd.Series:
        return _ema_allow(df, 55)

    def _slope(df: pd.DataFrame) -> pd.Series:
        return _slope_allow(df, 200)

    def _dual(df: pd.DataFrame) -> pd.Series:
        return _dual_ema_allow(df)

    def _nested(df: pd.DataFrame, _htf: str = htf, _etf: str = entry_tf) -> pd.Series:
        return _nested_allow(df, htf_agg=_htf, period=50, entry_tf=_etf)

    return {
        "sma": _sma,
        "ema": _ema,
        "slope": _slope,
        "dual": _dual,
        "nested": _nested,
    }


# Back-compat default builders (1h entry → 4h nested).
GATE_BUILDERS: dict[str, Callable[[pd.DataFrame], pd.Series]] = _gate_builders("1h")


def _max_drawdown(curve: list[dict[str, float]]) -> float:
    """Max drawdown as a positive fraction from the equity curve."""
    peak = 0.0
    max_dd = 0.0
    for point in curve:
        equity = point["equity"]
        if equity > peak:
            peak = equity
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
    return max_dd


def _sharpe(curve: list[dict[str, float]], bars_per_year: float = BARS_PER_YEAR) -> float:
    """Annualized Sharpe from per-bar equity returns (NaN-safe)."""
    equity = [p["equity"] for p in curve]
    if len(equity) < 3:
        return math.nan
    rets = pd.Series(equity).pct_change().dropna()
    if rets.std() == 0 or math.isnan(float(rets.std())):
        return math.nan
    return float(rets.mean() / rets.std() * math.sqrt(bars_per_year))


def aggregate(
    curve: list[dict[str, float]],
    fills: list[dict[str, object]],
    risk_events: list[dict[str, object]],
    alerts: list[dict[str, object]],
    capital: float,
    entry_tf: str = "1h",
) -> dict[str, object]:
    """Fold raw replay records into the report payload."""
    final_equity = curve[-1]["equity"] if curve else capital
    n_orders = len({f["order_id"] for f in fills})
    risk_by_reason: dict[str, int] = {}
    for ev in risk_events:
        reason = str(ev.get("reason", ev.get("type", "unknown")))
        risk_by_reason[reason] = risk_by_reason.get(reason, 0) + 1
    bpy = bars_per_year(entry_tf)
    sharpe = _sharpe(curve, bars_per_year=bpy)
    # Sample roughly once per day for the JSON payload.
    sample_every = max(1, int(bpy // 365.0) or 1)
    return {
        "bars": len(curve),
        "fills": len(fills),
        "orders": n_orders,
        "initial_capital": capital,
        "final_equity": round(final_equity, 4),
        "return_pct": round((final_equity / capital - 1.0) * 100.0, 4) if capital else 0.0,
        "max_drawdown_pct": round(_max_drawdown(curve) * 100.0, 4),
        "sharpe_annualized": round(sharpe, 4) if not math.isnan(sharpe) else None,
        "entry_tf": entry_tf,
        "bars_per_year": bpy,
        "risk_events": risk_by_reason,
        "alerts": alerts,
        "fills_detail": fills[:50],
        "equity_curve": curve[::sample_every],
    }
