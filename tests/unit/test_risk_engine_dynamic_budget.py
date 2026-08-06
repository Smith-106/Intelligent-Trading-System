"""Tests for RiskEngine dynamic (volatility-scaled) strategy budgets — s4 T-s4-01.

Default (dynamic_budget.enabled=False) must be byte-for-byte identical to the
static budget behavior; enabling scales budgets down when realized volatility
exceeds the target (fail-closed) and falls back to the static budget when the
return history is too short (fail-safe).
"""

from __future__ import annotations

import numpy as np

from quantflow.common.config import DynamicBudgetConfig, RiskConfig
from quantflow.common.models import Direction, Portfolio, Position, Signal
from quantflow.signal.risk_engine import RiskEngine


class TestDynamicBudgetDisabled:
    """enabled=False → static behavior unchanged (zero-change contract)."""

    def _engine(self) -> RiskEngine:
        return RiskEngine(
            RiskConfig(position_limit_pct=1.0),
            strategy_risk_budgets={"s1": 0.5},
        )

    def _signal(self) -> Signal:
        return Signal(
            symbol="BTC/USDT",
            direction=Direction.LONG,
            strength=0.8,
            price=100.0,
            strategy_id="s1",
        )

    def test_scale_budget_pct_returns_static_when_disabled(self) -> None:
        engine = self._engine()
        # Populate returns; even with high volatility the static budget is
        # returned unchanged because dynamic scaling is off.
        for _ in range(100):
            engine.add_return(0.05)
        assert engine._scale_budget_pct("s1", 0.5) == 0.5

    def test_check_still_enforces_static_budget(self) -> None:
        engine = self._engine()
        pos = Position("BTC/USDT", 1.0, 50000.0, 50000.0, strategy_id="s1")
        portfolio = Portfolio(cash=100000.0, positions={"BTC/USDT": pos})
        # s1 exposure=50000, total=150000, static budget=150000*0.5=75000 → passes
        assert engine.check(self._signal(), portfolio).passed

    def test_static_rejection_path_unchanged(self) -> None:
        engine = RiskEngine(
            RiskConfig(position_limit_pct=1.0),
            strategy_risk_budgets={"s1": 0.2},
        )
        pos = Position("BTC/USDT", 1.0, 50000.0, 50000.0, strategy_id="s1")
        portfolio = Portfolio(cash=100000.0, positions={"BTC/USDT": pos})
        result = engine.check(self._signal(), portfolio)
        assert result.passed is False
        assert result.reason == "strategy_budget"
        assert result.details["budget_pct"] == 0.2


class TestDynamicBudgetScaling:
    def _engine(self, **overrides: object) -> RiskEngine:
        cfg = DynamicBudgetConfig(
            enabled=True,
            target_vol_pct=0.15,
            min_scale=0.5,
            vol_annualization=365,
            vol_ewma_span=30,
            min_samples=30,
            **overrides,  # max_scale defaults to 1.5 (pydantic) unless overridden
        )
        return RiskEngine(
            RiskConfig(position_limit_pct=1.0, dynamic_budget=cfg),
            strategy_risk_budgets={"s1": 0.5},
        )

    def _signal(self) -> Signal:
        return Signal(
            symbol="BTC/USDT",
            direction=Direction.LONG,
            strength=0.8,
            price=100.0,
            strategy_id="s1",
        )

    def _portfolio(self) -> Portfolio:
        pos = Position("BTC/USDT", 1.0, 50000.0, 50000.0, strategy_id="s1")
        return Portfolio(cash=100000.0, positions={"BTC/USDT": pos})

    def test_high_volatility_shrinks_budget(self) -> None:
        engine = self._engine()
        # Very volatile returns → realized vol >> target → scale=max_scale=1.5
        rng = np.random.default_rng(42)
        for r in rng.normal(0.0, 0.02, 200):
            engine.add_return(float(r))
        scaled = engine._scale_budget_pct("s1", 0.5)
        assert scaled < 0.5
        assert scaled >= 0.5 / 1.5

    def test_low_volatility_keeps_budget(self) -> None:
        engine = self._engine()
        # Tiny returns → realized vol << target → scale stays at 1.0 floor
        rng = np.random.default_rng(1)
        for r in rng.normal(0.0, 0.0001, 200):
            engine.add_return(float(r))
        scaled = engine._scale_budget_pct("s1", 0.5)
        assert scaled == 0.5  # max(1.0, vol/target) → 1.0

    def test_insufficient_history_falls_back_to_static(self) -> None:
        engine = self._engine()
        for r in [0.01] * 10:  # only 10 samples < min_samples=30
            engine.add_return(r)
        assert engine._scale_budget_pct("s1", 0.5) == 0.5

    def test_zero_std_returns_falls_back_to_static(self) -> None:
        engine = self._engine()
        for _ in range(50):
            engine.add_return(0.0)
        assert engine._scale_budget_pct("s1", 0.5) == 0.5

    def test_clamp_respects_max_scale(self) -> None:
        engine = self._engine(max_scale=1.2)
        rng = np.random.default_rng(7)
        for r in rng.normal(0.0, 0.05, 200):
            engine.add_return(float(r))
        scaled = engine._scale_budget_pct("s1", 0.5)
        assert scaled >= 0.5 / 1.2 - 1e-9

    def test_dynamic_scaling_can_flip_rejection(self) -> None:
        """A position under the static budget is rejected once volatility
        scaling shrinks the budget below the current exposure."""
        engine = self._engine()
        pos = Position("BTC/USDT", 1.0, 50000.0, 50000.0, strategy_id="s1")
        portfolio = Portfolio(cash=100000.0, positions={"BTC/USDT": pos})
        # Exposure=50000 of total=150000 → 33.3%; static budget 50% passes.
        assert engine.check(self._signal(), portfolio).passed
        # High volatility shrinks budget to 50%/1.5 = 33.3% floor → blocks.
        rng = np.random.default_rng(42)
        for r in rng.normal(0.0, 0.02, 200):
            engine.add_return(float(r))
        result = engine.check(self._signal(), portfolio)
        assert result.passed is False
        assert result.reason == "strategy_budget"
        assert result.details["budget_pct"] < 0.5
