"""Coverage closure: risk_engine.py + position_sizer.py + book_risk_budget.py."""

from __future__ import annotations

import numpy as np
import pytest

from quantflow.common.config import DynamicBudgetConfig, RiskConfig
from quantflow.common.models import Direction, Portfolio, Position, Signal
from quantflow.signal.book_risk_budget import BookRiskBudget
from quantflow.signal.position_sizer import PositionSizer
from quantflow.signal.portfolio import PendingView
from quantflow.signal.risk_engine import RiskEngine


# ===========================================================================
# risk_engine.py
# ===========================================================================


def test_risk_engine_exchange_exposure_total_zero_and_zero_price_positions() -> None:
    engine = RiskEngine(RiskConfig(), exchange_exposure_limit_pct=0.5)
    sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
    assert engine._check_exchange_exposure(sig, Portfolio(cash=0)).passed  # 195
    pf = Portfolio(cash=100000, positions={"BTC/USDT": Position("BTC/USDT", 1.0, 50000, 0.0)})
    assert engine._check_exchange_exposure(sig, pf).passed  # 198->197 price<=0 skipped


def test_risk_engine_book_risk_budget_branches() -> None:
    budget = BookRiskBudget(
        book_gross_limit=2.0,
        book_net_limit=2.0,
        strategy_limits={"beta": 1.0},
        factor_sleeve_limits={"beta": 1.5, "overlay": 0.1},
    )
    engine = RiskEngine(RiskConfig(), book_risk_budget=budget)

    sig_short = Signal("BTC/USDT", Direction.SHORT, 0.8, 50000)
    assert engine._check_book_risk_budget(sig_short, Portfolio(cash=100000)).passed  # 223

    sig_long = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
    assert engine._check_book_risk_budget(sig_long, Portfolio(cash=0)).passed  # 227

    pf = Portfolio(
        cash=50000,
        positions={
            "BTC/USDT": Position("BTC/USDT", 1.0, 50000, 50000),
            "ETH/USDT": Position("ETH/USDT", 1.0, 1000, 0.0),  # 232-233 zero price
        },
    )
    pending = PendingView(total=1000, by_symbol={"ETH/USDT": 1000}, by_strategy={})
    sig_beta = Signal("BTC/USDT", Direction.LONG, 0.8, 50000, strategy_id="beta")
    res = engine._check_book_risk_budget(sig_beta, pf, pending)
    assert res.passed  # 232-236, 238-240, 251-252, 267

    # strategy_id without overlay/beta/hodl keywords -> sleeve stays None (251->254).
    sig_plain = Signal("BTC/USDT", Direction.LONG, 0.8, 50000, strategy_id="trend")
    res_plain = engine._check_book_risk_budget(sig_plain, pf, pending)
    assert res_plain.passed


def test_risk_engine_position_limit_with_pending() -> None:
    engine = RiskEngine(RiskConfig(position_limit_pct=0.2, max_positions=5))
    pf = Portfolio(cash=50000, positions={"BTC/USDT": Position("BTC/USDT", 1.0, 50000, 50000)})
    pending = PendingView(
        total=30000, by_symbol={"BTC/USDT": 10000, "ETH/USDT": 20000}, by_strategy={}
    )
    sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
    res = engine._check_position_limit(sig, pf, pending)
    assert not res.passed and res.reason == "position_limit"  # 284 + 286-291

    sig2 = Signal("ETH/USDT", Direction.LONG, 0.8, 50000)
    res2 = engine._check_position_limit(sig2, pf, pending)
    assert not res2.passed and res2.reason == "position_limit"  # 292-300 new pending symbol

    sig3 = Signal("SOL/USDT", Direction.LONG, 0.8, 50000)
    res3 = engine._check_position_limit(sig3, pf, pending)
    assert res3.passed  # pending symbol absent -> fall through

    # Pending exposure below the limit -> elif False edge (297->303).
    engine2 = RiskEngine(RiskConfig(position_limit_pct=0.9, max_positions=5))
    pending_small = PendingView(total=5000, by_symbol={"ETH/USDT": 5000}, by_strategy={})
    res4 = engine2._check_position_limit(sig2, pf, pending_small)
    assert res4.passed


def test_risk_engine_portfolio_limit_pending_new_symbol() -> None:
    engine = RiskEngine(RiskConfig(max_positions=2))
    pf = Portfolio(cash=50000, positions={"BTC/USDT": Position("BTC/USDT", 1.0, 50000, 50000)})
    pending = PendingView(total=1000, by_symbol={"ETH/USDT": 1000}, by_strategy={})
    sig = Signal("ETH/USDT", Direction.LONG, 0.8, 50000)
    res = engine._check_portfolio_limit(sig, pf, pending)
    assert not res.passed and res.reason == "max_positions"  # 312-313

    # Pending symbol already in positions -> 312->311 False edge (no increment).
    pending2 = PendingView(total=1000, by_symbol={"BTC/USDT": 1000}, by_strategy={})
    res2 = engine._check_portfolio_limit(sig, pf, pending2)
    assert res2.passed  # effective_count stays 1 < max_positions


def test_risk_engine_dynamic_budget_cvar_scale_false_edge() -> None:
    cfg = RiskConfig()
    cfg.dynamic_budget = DynamicBudgetConfig(enabled=True, var_scaling=True)
    engine = RiskEngine(cfg, strategy_risk_budgets={"trend": 0.2})
    for i in range(30):
        engine.add_return(0.01 if i % 2 else 0.02)  # positive + varied -> cvar > 0
    engine._check_var(
        Signal("BTC/USDT", Direction.LONG, 0.8, 50000), Portfolio(cash=100000)
    )
    assert engine._scale_budget_pct("trend", 0.2) > 0  # 425->428 (cvar < 0 False)


def test_risk_engine_var_cache_hit() -> None:
    engine = RiskEngine(RiskConfig())
    sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
    pf = Portfolio(cash=100000)
    for i in range(30):
        engine.add_return(-0.01 if i % 3 == 0 else 0.005)
    engine.check(sig, pf)
    engine.check(sig, pf)  # second run hits _var_cache (506)
    assert engine._var_cache_len == 30


# ===========================================================================
# position_sizer.py
# ===========================================================================


def test_position_sizer_realized_vol_nan_and_opposite_direction() -> None:
    sizer = PositionSizer(vol_target_pct=0.2, vol_window=2)
    sizer.add_return(float("nan"))
    sizer.add_return(float("nan"))
    assert sizer._realized_vol() is None  # 83 (all-NaN window)

    sig_long = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
    pf = Portfolio(cash=100000, positions={"BTC/USDT": Position("BTC/USDT", -1.0, 50000, 50000)})
    size = sizer.size(sig_long, pf)
    assert size > 0  # 176->180 same_direction False -> no deduction

    assert sizer.size(sig_long, Portfolio(cash=0)) == 0.0  # total_value <= 0


# ===========================================================================
# book_risk_budget.py
# ===========================================================================


def test_book_risk_budget_validation_and_layers() -> None:
    with pytest.raises(ValueError):
        BookRiskBudget(book_gross_limit=0)  # 40
    with pytest.raises(ValueError):
        BookRiskBudget(book_net_limit=0)  # 42
    with pytest.raises(ValueError):
        BookRiskBudget(kill_drawdown=0)  # 44 (already covered, keep for completeness)
    with pytest.raises(ValueError):
        BookRiskBudget(strategy_limits={"x": -1.0})  # 47

    b = BookRiskBudget(strategy_limits={"trend": 0.2}, factor_sleeve_limits={"beta": 0.5})
    assert "book_gross_limit" in b.to_dict()  # 50

    res = b.check(equity=0, current_gross=0, current_net=0, proposed_notional_delta=100)
    assert res["reason"] == "non_positive_equity"  # 73

    res2 = b.check(equity=1000, current_gross=1000, current_net=0, proposed_notional_delta=5000)
    assert res2["reason"] == "book_gross"  # 116

    res3 = b.check(equity=1000, current_gross=0, current_net=900, proposed_notional_delta=200)
    assert res3["reason"] == "book_net"  # 129

    res4 = b.check(
        equity=1000,
        current_gross=0,
        current_net=0,
        proposed_notional_delta=100,
        strategy_id="trend",
        strategy_current_notional=0,
    )
    assert res4["allowed"]  # 144->147 strategy ok + 147->163 no sleeve
    assert any(l["layer"] == "strategy" for l in res4["layers"])

    res5 = b.check(
        equity=1000,
        current_gross=0,
        current_net=0,
        proposed_notional_delta=100,
        sleeve="beta",
        sleeve_current_notional=600,
    )
    assert res5["reason"] == "sleeve_limit"  # 161 rejection

    res6 = b.check(
        equity=1000,
        current_gross=0,
        current_net=0,
        proposed_notional_delta=100,
        sleeve="beta",
        sleeve_current_notional=0,
    )
    assert res6["allowed"]
