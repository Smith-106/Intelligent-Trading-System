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
from quantflow.strategy.templates.mean_reversion import MeanReversionStrategy
from quantflow.strategy.templates.trend_following import TrendFollowingStrategy
from quantflow.strategy.templates.volatility_breakout import VolatilityBreakoutStrategy

STRATEGIES = {
    "trend_following": TrendFollowingStrategy,
    "mean_reversion": MeanReversionStrategy,
    "volatility_breakout": VolatilityBreakoutStrategy,
}

BARS_PER_YEAR = 24 * 365  # 1h bars


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
) -> TradingSession:
    """Build a paper TradingSession with PaperGateway injected directly,
    bypassing start()'s Prometheus/network init and live data loop.

    The session's ExecutionEngine is rebuilt with the gateway bound at
    construction (OrderRouter binds in __init__; bypassing start() skips
    set_gateway) and the A2 (ISS-20260803-003) seams threaded through: the
    exchange health monitor + shared sink stay attached.
    """
    cfg = config or AppConfig()
    cfg.execution.mode = "paper"
    # Replay is a controlled simulation, not live — no kill switch, no
    # drawdown trip mid-replay.
    cfg.risk.kill_switch_enabled = False
    cfg.risk.max_drawdown = -0.90

    strategy_cls = STRATEGIES.get(strategy_name)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy '{strategy_name}'. Available: {list(STRATEGIES)}")
    strategy = strategy_cls(params=params)  # type: ignore[abstract]
    session = TradingSession(cfg, [strategy], monitoring_sink=sink)
    session._execution = ExecutionEngine(
        event_bus=session._event_bus,
        gateway=PaperGateway({"initial_capital": capital, "taker_fee": cfg.execution.taker_fee}),
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


async def replay(
    session: TradingSession,
    bars_df: pd.DataFrame,
    symbol: str,
    fills: list[dict[str, object]] | None = None,
    risk_events: list[dict[str, object]] | None = None,
    direction_gate: bool | str = False,
    gate_sma_period: int = 200,
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
        if gate_name not in GATE_BUILDERS:
            raise ValueError(f"Unknown gate '{gate_name}'. Available: {list(GATE_BUILDERS)}")
        allow = GATE_BUILDERS[gate_name](bars_df)
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


def _nested_allow(df: pd.DataFrame, htf_agg: str = "4h", period: int = 50) -> pd.Series:
    """Gate A/a: higher-timeframe direction gate over lower-timeframe entries.

    Aggregates the 1h bars into ``htf_agg`` buckets, computes SMA(period) on
    the HTF close, and opens the gate only while the *previous completed* HTF
    bar's close is >= its SMA — the HTF value is visible to the LTF only
    after the HTF bar closes (no look-ahead; M3-P0 constraint).
    """
    close = df["close"]
    # Bucket each 1h row into its HTF period (e.g. 4h): row i belongs to
    # bucket i // htf_bars. The gate uses the bucket *before* the current
    # one, so the HTF bar must be complete.
    htf_bars = 4 if htf_agg == "4h" else 24
    htf_close = close.groupby(close.index // htf_bars).transform("last")
    htf_sma = htf_close.rolling(period * htf_bars).mean()
    # Previous bucket's value (shift by one bucket = htf_bars rows).
    prev_htf_close = htf_close.shift(htf_bars)
    prev_htf_sma = htf_sma.shift(htf_bars)
    return prev_htf_close.fillna(0) >= prev_htf_sma.fillna(float("-inf"))


GATE_BUILDERS: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    "sma": lambda df: _sma_allow(df, 200),
    "ema": lambda df: _ema_allow(df, 55),
    "slope": lambda df: _slope_allow(df, 200),
    "dual": lambda df: _dual_ema_allow(df),
    "nested": lambda df: _nested_allow(df, "4h", 50),
}


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
) -> dict[str, object]:
    """Fold raw replay records into the report payload."""
    final_equity = curve[-1]["equity"] if curve else capital
    n_orders = len({f["order_id"] for f in fills})
    risk_by_reason: dict[str, int] = {}
    for ev in risk_events:
        reason = str(ev.get("reason", ev.get("type", "unknown")))
        risk_by_reason[reason] = risk_by_reason.get(reason, 0) + 1
    sharpe = _sharpe(curve)
    return {
        "bars": len(curve),
        "fills": len(fills),
        "orders": n_orders,
        "initial_capital": capital,
        "final_equity": round(final_equity, 4),
        "return_pct": round((final_equity / capital - 1.0) * 100.0, 4) if capital else 0.0,
        "max_drawdown_pct": round(_max_drawdown(curve) * 100.0, 4),
        "sharpe_annualized": round(sharpe, 4) if not math.isnan(sharpe) else None,
        "risk_events": risk_by_reason,
        "alerts": alerts,
        "fills_detail": fills[:50],
        "equity_curve": curve[::24],  # sample daily for the JSON payload
    }
