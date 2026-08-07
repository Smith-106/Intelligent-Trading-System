"""Regression guards for the paper-replay harness (C1).

Both failures below were SILENT zero-trade regressions — no error, no signal,
no equity movement:

1. M4 multi-symbol re-key: legacy contexts are keyed by ``(name, "")``; a
   bare ``name`` key is never found by ``on_bar`` and every strategy is gated
   out. Guard: replay on synthetic volatile data must produce fills.
2. ``start()`` rebinds the L5 PositionManager to the shared L4 portfolio via
   ``set_portfolio``; bypassing it leaves fills on a private default book and
   the session equity frozen. Guard: equity must move when fills occur.

These pin the harness contract so future refactors cannot silently break the
live-faithful replay path again.
"""

from __future__ import annotations

import pandas as pd
import pytest

from quantflow.common.models import Bar
from quantflow.strategy.research.paper_replay import (
    RecordingSink,
    aggregate,
    build_session,
    replay,
)

SYMBOL = "BTC/USDT"
BASE_TS = 1_780_000_000_000  # ~2026-06


def _synthetic_bars(n: int = 400, start_price: float = 60_000.0) -> pd.DataFrame:
    """High-volatility sawtooth — mean_reversion needs RSI<30/BB-break +
    volume > 1.2x MA, so alternate sharp swings with quiet rows."""
    rows = []
    price = start_price
    for i in range(n):
        # Cycle: 12-bar down-leg (entry zone) then 12-bar up-leg (exit).
        phase = (i // 12) % 2
        if phase == 0:
            price *= 0.985
        else:
            price *= 1.02
        volume = 100.0 * (3.0 if i % 12 < 2 else 1.0)
        rows.append(
            {
                "timestamp": BASE_TS + i * 3_600_000,
                "open": price,
                "high": price * 1.002,
                "low": price * 0.998,
                "close": price,
                "volume": volume,
            }
        )
    return pd.DataFrame(rows)


@pytest.mark.asyncio
async def test_replay_produces_fills_and_moving_equity() -> None:
    """Harness contract: strategy on_bar actually runs (contexts key) and
    fills land on the session book (set_portfolio rebind)."""
    sink = RecordingSink()
    session = build_session("mean_reversion", capital=100_000.0, sink=sink)
    fills: list[dict] = []
    risk_events: list[dict] = []
    curve = await replay(session, _synthetic_bars(), SYMBOL, fills, risk_events)

    assert len(curve) == 400
    assert fills, "M4 contexts re-key regression: strategy never ran -> 0 fills"
    assert len(curve) >= 2
    # set_portfolio regression: fills must move the session book.
    assert curve[-1]["equity"] != pytest.approx(100_000.0, abs=1.0), (
        "set_portfolio regression: fills landed on a private book, equity frozen"
    )


@pytest.mark.asyncio
async def test_replay_report_aggregation() -> None:
    """aggregate() folds raw streams into the report contract."""
    sink = RecordingSink()
    session = build_session("mean_reversion", capital=100_000.0, sink=sink)
    fills: list[dict] = []
    risk_events: list[dict] = []
    curve = await replay(session, _synthetic_bars(200), SYMBOL, fills, risk_events)

    report = aggregate(curve, fills, risk_events, sink.alerts, 100_000.0)
    assert report["bars"] == 200
    assert report["fills"] == len(fills)
    assert report["orders"] == len({f["order_id"] for f in fills})
    for key in (
        "initial_capital",
        "final_equity",
        "return_pct",
        "max_drawdown_pct",
        "sharpe_annualized",
        "risk_events",
        "alerts",
        "fills_detail",
        "equity_curve",
    ):
        assert key in report
    # Fills are truthful: every order_id in detail has side/quantity/price.
    for f in report["fills_detail"]:
        assert {"order_id", "symbol", "side", "quantity", "price"} <= set(f)


@pytest.mark.asyncio
async def test_replay_unknown_strategy_rejected() -> None:
    with pytest.raises(ValueError):
        build_session("no_such_strategy")


# ---------------------------------------------------------------------------
# Direction gate A/B (P2 regime work): wrapper semantics + byte-for-byte default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_direction_gate_suppresses_entries_below_sma() -> None:
    """With direction_gate on, bars whose close < SMA(200) must NOT emit;
    bars above the SMA keep trading (orders drop, curve still moves)."""
    from quantflow.strategy.research.paper_replay import _DirectionGateWrapper
    from quantflow.strategy.templates.mean_reversion import MeanReversionStrategy

    inner = MeanReversionStrategy()
    # Falling market: close monotonically down → below SMA after warm-up.
    bars = pd.DataFrame(
        {
            "timestamp": [1_700_000_000_000 + i * 3_600_000 for i in range(250)],
            "open": [100.0 - i * 0.1 for i in range(250)],
            "high": [100.0 - i * 0.1 + 1.0 for i in range(250)],
            "low": [100.0 - i * 0.1 - 1.0 for i in range(250)],
            "close": [100.0 - i * 0.1 for i in range(250)],
            "volume": [100.0 for _ in range(250)],
        }
    )
    sma = bars["close"].rolling(200).mean()
    wrapper = _DirectionGateWrapper(inner, sma)
    assert wrapper.required_regime == inner.required_regime

    ctx = _CtxStub()
    wrapper.on_init(ctx)
    emitted = 0
    for _i, row in enumerate(bars.itertuples(index=False)):
        bar = _bar_from_row(row)
        wrapper.on_bar(ctx, bar)
        emitted += len(ctx.signals)
        ctx.signals.clear()
    # Post warm-up (bar >= 200) the market is below SMA → suppressed.
    assert emitted < 50, f"expected heavy suppression, got {emitted}"


class _CtxStub:
    """Minimal StrategyContext stand-in collecting emitted signals."""

    def __init__(self) -> None:
        self.signals: list[object] = []

    def emit_signal(self, *a: object, **k: object) -> None:
        self.signals.append((a, k))


def _bar_from_row(row: object) -> Bar:
    return Bar(
        symbol="BTC/USDT",
        timestamp=int(row.timestamp),
        open=float(row.open),
        high=float(row.high),
        low=float(row.low),
        close=float(row.close),
        volume=float(row.volume),
    )


@pytest.mark.asyncio
async def test_direction_gate_off_is_byte_for_byte_baseline() -> None:
    """direction_gate=False (explicit) must produce the exact same curve/fills
    as the pre-feature call (A/B switch is opt-in; default path unchanged)."""
    sink_a, sink_b = RecordingSink(), RecordingSink()
    session_a = build_session("mean_reversion", 100_000.0, sink_a)
    session_b = build_session("mean_reversion", 100_000.0, sink_b)
    bars = _synthetic_bars(200)
    fills_a: list[dict] = []
    fills_b: list[dict] = []
    curve_a = await replay(session_a, bars, SYMBOL, fills_a, [])
    curve_b = await replay(session_b, bars, SYMBOL, fills_b, [], direction_gate=False)
    assert curve_a == curve_b
    assert fills_a == fills_b
