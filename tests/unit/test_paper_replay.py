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
