"""Tests for benchmark excess + book risk budget (highflyer-style layers)."""

from __future__ import annotations

import pandas as pd
import pytest

from quantflow.signal.book_risk_budget import (
    BookRiskBudget,
    default_highflyer_style_budget,
)
from quantflow.strategy.research.benchmark_excess import (
    buy_hold_equity_from_close,
    equity_stats,
    excess_vs_benchmark,
    gate_beats_benchmark,
)


def test_buy_hold_and_excess_beats() -> None:
    close = pd.Series([100.0, 110.0, 121.0])
    b = buy_hold_equity_from_close(close)
    # strategy compounds faster than buy-hold (not a constant scale of b)
    s = pd.Series([1.0, 1.15, 1.40])
    rep = excess_vs_benchmark(s, b, label="s", benchmark_label="bh")
    assert rep.n_bars == 3
    assert rep.benchmark_return_pct == pytest.approx(21.0, rel=1e-6)
    assert rep.strategy_return_pct == pytest.approx(40.0, rel=1e-6)
    assert rep.excess_return_pct > 0
    assert rep.beats_benchmark is True
    g = gate_beats_benchmark(rep)
    assert g["decision"] == "PASS"


def test_excess_fails_when_under_benchmark() -> None:
    b = pd.Series([1.0, 1.2, 1.5])
    s = pd.Series([1.0, 1.05, 1.1])
    rep = excess_vs_benchmark(s, b)
    assert rep.beats_benchmark is False
    assert gate_beats_benchmark(rep)["decision"] == "FAIL"


def test_equity_stats_drawdown() -> None:
    eq = pd.Series([1.0, 1.2, 0.9, 1.0])
    st = equity_stats(eq)
    assert st["max_dd_pct"] == pytest.approx(25.0, rel=1e-6)


def test_book_budget_kill_and_sleeves() -> None:
    bud = default_highflyer_style_budget(overlay_sleeve=0.2, kill_drawdown=0.15)
    equity = 100_000.0
    # kill
    r = bud.check(
        equity=equity,
        current_gross=0.0,
        current_net=0.0,
        proposed_notional_delta=1000.0,
        current_drawdown=0.20,
        risk_increasing=True,
        sleeve="overlay",
        sleeve_current_notional=0.0,
    )
    assert r["allowed"] is False
    assert r["reason"] == "kill_drawdown"

    # overlay sleeve cap 20%
    r2 = bud.check(
        equity=equity,
        current_gross=0.0,
        current_net=0.0,
        proposed_notional_delta=25_000.0,  # 25% > 20%
        current_drawdown=0.0,
        sleeve="overlay",
        sleeve_current_notional=0.0,
    )
    assert r2["allowed"] is False
    assert r2["reason"] == "sleeve_limit"

    r3 = bud.check(
        equity=equity,
        current_gross=0.0,
        current_net=0.0,
        proposed_notional_delta=15_000.0,
        current_drawdown=0.0,
        sleeve="overlay",
        sleeve_current_notional=0.0,
    )
    assert r3["allowed"] is True


def test_book_budget_strategy_limit() -> None:
    bud = BookRiskBudget(
        book_gross_limit=1.0,
        book_net_limit=1.0,
        strategy_limits={"trend": 0.3},
        kill_drawdown=0.5,
    )
    r = bud.check(
        equity=10_000.0,
        current_gross=0.0,
        current_net=0.0,
        proposed_notional_delta=4_000.0,
        strategy_id="trend",
        strategy_current_notional=0.0,
    )
    assert r["allowed"] is False
    assert r["reason"] == "strategy_limit"


def test_invalid_budget() -> None:
    with pytest.raises(ValueError):
        BookRiskBudget(kill_drawdown=0.0)


def test_risk_engine_optional_book_budget_kill() -> None:
    from quantflow.common.config import RiskConfig
    from quantflow.common.models import Direction, Portfolio, Signal
    from quantflow.signal.risk_engine import RiskEngine

    eng = RiskEngine(
        RiskConfig(),
        book_risk_budget=BookRiskBudget(
            kill_drawdown=0.10, book_gross_limit=2.0, book_net_limit=2.0
        ),
    )
    port = Portfolio(cash=100_000.0, positions={}, current_drawdown=0.20)
    sig = Signal(
        symbol="BTC/USDT",
        direction=Direction.LONG,
        strength=0.5,
        price=50_000.0,
        strategy_id="overlay_trend",
        timestamp=0,
    )
    decision = eng.check(sig, port)
    assert decision.passed is False
    assert decision.reason and "book_risk_budget" in decision.reason

    # Without budget: same signal/port should not fail on book budget
    eng2 = RiskEngine(RiskConfig())
    # may still fail other checks; drawdown 0.20 might trip default DD — set mild
    port2 = Portfolio(cash=100_000.0, positions={}, current_drawdown=0.0)
    d2 = eng2.check(sig, port2)
    assert d2.passed is True
