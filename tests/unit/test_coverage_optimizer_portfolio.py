"""Coverage closure: optimizer.py (signal) + portfolio.py."""

from __future__ import annotations

import numpy as np
import pytest

from quantflow.common.models import Direction, Portfolio, Position, Signal
from quantflow.signal import optimizer as optimizer_module
from quantflow.signal.optimizer import MeanVarianceOptimizer, RiskParityOptimizer
from quantflow.signal.portfolio import PortfolioManager


# ===========================================================================
# optimizer.py
# ===========================================================================


def _rp_series_a() -> list[float]:
    return [0.01, 0.02, 0.01, 0.02, 0.01]


def _rp_series_b() -> list[float]:
    return [0.03, 0.01, 0.03, 0.01, 0.03]


def test_risk_parity_optimizer_degenerate_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    opt = RiskParityOptimizer(min_samples=2)
    assert opt.equal_weight([]) == {}

    # All-NaN series -> _annualized_vol returns None (line 58).
    returns = {"A": [float("nan")] * 2, "B": _rp_series_b()}
    w = opt.compute(returns)
    assert w == {"A": 0.5, "B": 0.5}

    # Solver reports failure -> warning + equal weights (111-112).
    class _FailResult:
        success = False
        message = "Positive directional derivative"

    monkeypatch.setattr(optimizer_module, "minimize", lambda *a, **k: _FailResult())
    w2 = opt.compute({"A": _rp_series_a(), "B": _rp_series_b()})
    assert w2 == {"A": 0.5, "B": 0.5}

    # Success but all-negative weights -> clip -> total 0 (116).
    class _NegResult:
        success = True
        x = [-1.0, -1.0]

    monkeypatch.setattr(optimizer_module, "minimize", lambda *a, **k: _NegResult())
    w3 = opt.compute({"A": _rp_series_a(), "B": _rp_series_b()})
    assert w3 == {"A": 0.5, "B": 0.5}

    # Unexpected solver exception -> logger.exception + equal weights (118-120).
    def _boom(*a, **k):
        raise RuntimeError("solver crashed")

    monkeypatch.setattr(optimizer_module, "minimize", _boom)
    w4 = opt.compute({"A": _rp_series_a(), "B": _rp_series_b()})
    assert w4 == {"A": 0.5, "B": 0.5}


def test_mean_variance_optimizer_fault_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    opt = MeanVarianceOptimizer(min_samples=2)
    returns = {"A": [0.01, 0.02, 0.03, 0.01], "B": [0.03, 0.04, 0.02, 0.05]}

    # Singular covariance -> pinv fallback (186) still yields weights.
    w = opt.compute({"A": [0.01, 0.02], "B": [0.03, 0.04]})
    assert abs(sum(w.values()) - 1.0) < 1e-6

    # Non-finite inverse output -> equal weights (191).
    monkeypatch.setattr(np.linalg, "inv", lambda cov: np.full((2, 2), np.nan))
    w2 = opt.compute(returns)
    assert w2 == {"A": 0.5, "B": 0.5}

    # Unexpected exception from linalg -> outer except (197-199).
    def _bad_inv(cov):
        raise ValueError("covariance exploded")

    monkeypatch.setattr(np.linalg, "inv", _bad_inv)
    w3 = opt.compute(returns)
    assert w3 == {"A": 0.5, "B": 0.5}

    # Degenerate inputs -> equal weights over original keys.
    assert opt.compute({"A": [0.01] * 4}) == {"A": 1.0}
    assert opt.compute({"A": [0.01] * 4, "B": [0.01] * 4}) == {"A": 0.5, "B": 0.5}  # zero variance


# ===========================================================================
# portfolio.py
# ===========================================================================


def test_portfolio_manager_allocation_helpers() -> None:
    pm = PortfolioManager(100000.0)
    pm.set_capital_baseline(200000.0)  # 249-251
    assert pm._current_drawdown == 0.0

    assert pm.get_strategy_allocation("") == 0.0  # 283
    assert pm.get_strategy_allocation("nope") == 0.0  # 286 simple-id path

    pm.set_allocation({"trend": 0.4, "momentum": 0.3})
    assert pm.get_strategy_allocation("trend") == 0.4
    assert pm.get_strategy_allocation("trend,momentum") == 0.7  # compound sum
    assert pm.get_strategy_allocation(",") == 0.0  # empty constituents

    assert pm.get_symbol_allocation("BTC/USDT") == 1.0  # 296 unset -> 1.0
    pm.set_symbol_allocation({"BTC/USDT": 0.5})
    assert pm.get_symbol_allocation("BTC/USDT") == 0.5
    assert pm.get_symbol_allocation("ETH/USDT") == 0.0

    pm.add_symbol_return("", 0.01)  # 346 empty symbol -> early return
    pm.add_symbol_return("BTC/USDT", 0.01)
    pm.add_symbol_return("BTC/USDT", -0.005)
    assert pm.get_symbol_returns()["BTC/USDT"] == [0.01, -0.005]
    assert "SOL/USDT" not in pm.get_symbol_returns()


def test_portfolio_manager_budget_utilization_and_pending() -> None:
    pm = PortfolioManager(100000.0)
    pm.update_position("BTC/USDT", 2.0, 50000.0, strategy_id="trend")
    pm.update_position("ETH/USDT", 1.0, 0.0, strategy_id="trend")  # zero price -> 369 continue
    pm.set_allocation({"trend": 0.5})
    report = pm.budget_utilization()
    assert "trend" in report
    assert report["trend"]["exposure_notional"] == 100000.0

    pm.reserve("o1", "BTC/USDT", 1000.0, strategy_id="trend")
    pm.reserve("o2", "ETH/USDT", 500.0, strategy_id="")  # 484->482 empty strategy_id
    view = pm.pending_view()
    assert view.total == 1500.0
    assert view.by_symbol["BTC/USDT"] == 1000.0
    assert "ETH/USDT" not in view.by_strategy

    pm.partial_confirm("missing", 1.0)  # 447 entry None -> early return
    pm.partial_confirm("o1", 400.0)  # remaining 600 > epsilon
    assert pm.total_pending_exposure == 1100.0
    pm.partial_confirm("o2", 500.0)  # remaining <= epsilon -> removed
    assert pm.total_pending_exposure == 600.0


def test_portfolio_manager_drawdown_zero_peak() -> None:
    pm = PortfolioManager(0.0)  # peak equity 0 -> 413->exit branch
    pm.update_position("BTC/USDT", 1.0, 100.0)
    assert pm._current_drawdown == 0.0
    assert pm.snapshot()["drawdown"] == 0.0
