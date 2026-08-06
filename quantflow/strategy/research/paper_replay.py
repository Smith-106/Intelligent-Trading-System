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

import pandas as pd

from quantflow.common.config import AppConfig
from quantflow.common.event_bus import EVENT_FILL, EVENT_RISK
from quantflow.common.models import Bar
from quantflow.common.monitoring_sink import NullMonitoringSink
from quantflow.execution.engine import ExecutionEngine
from quantflow.execution.paper_gateway import PaperGateway
from quantflow.strategy.base import StrategyContext
from quantflow.strategy.engine import TradingSession
from quantflow.strategy.templates.mean_reversion import MeanReversionStrategy
from quantflow.strategy.templates.trend_following import TrendFollowingStrategy

STRATEGIES = {
    "trend_following": TrendFollowingStrategy,
    "mean_reversion": MeanReversionStrategy,
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
    session = TradingSession(cfg, [strategy_cls()], monitoring_sink=sink)
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
) -> list[dict[str, float]]:
    """Feed each bar through on_bar; return the per-bar equity curve.

    ``fills`` / ``risk_events`` are appended to in place (caller-owned) so the
    caller can inspect the raw event streams alongside the curve.
    """
    fills = fills if fills is not None else []
    risk_events = risk_events if risk_events is not None else []

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
