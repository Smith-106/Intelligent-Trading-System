"""Tests for s5 CVaR-based budget scaling in the risk engine."""

from __future__ import annotations

from quantflow.common.config import DynamicBudgetConfig, RiskConfig
from quantflow.common.models import Direction, Portfolio, Signal
from quantflow.signal.risk_engine import RiskEngine


def _signal() -> Signal:
    return Signal(symbol="BTC/USDT", direction=Direction.LONG, strength=0.5, strategy_id="trend")


def _portfolio() -> Portfolio:
    return Portfolio(cash=100000.0, positions={}, current_drawdown=0.0)


def _engine_with_var_history(
    cvar_value: float, *, var_scaling: bool, history: list[float] | None = None
) -> RiskEngine:
    """Engine with a pre-populated returns history and cached CVaR.

    The CVaR cache is computed via _check_var: feed a history whose
    historical CVaR (95%) approximates ``cvar_value``, then run one
    check so the cache is populated.
    """
    config = RiskConfig(cvar_limit=-0.05)
    config.dynamic_budget = DynamicBudgetConfig(
        enabled=True, var_scaling=var_scaling, min_samples=5
    )
    engine = RiskEngine(config, strategy_risk_budgets={"trend": 0.30})
    # 30 calm bars + 30 bars at -0.10: 95% CVaR ≈ -0.10 (tail is the -0.10s),
    # so the cvar factor |−0.10|/|−0.05| = 2.0 applies when enabled.
    hist = history or [0.0] * 30 + [-0.10] * 30
    for r in hist:
        engine.add_return(r)
    engine.check(_signal(), _portfolio())
    return engine


class TestVarScaling:
    def test_cvar_worse_than_limit_shrinks_budget(self) -> None:
        """CVaR = -0.10 vs limit -0.05 → budget scales down ~2x."""
        engine = _engine_with_var_history(-0.10, var_scaling=True)
        scaled = engine._scale_budget_pct("trend", 0.30)
        # Vol scaling (1.0 min) * cvar scaling (|−0.10|/|−0.05| = 2.0).
        assert scaled <= 0.15 + 1e-9
        assert scaled > 0.0

    def test_var_scaling_disabled_unchanged(self) -> None:
        engine = _engine_with_var_history(-0.10, var_scaling=False)
        scaled = engine._scale_budget_pct("trend", 0.30)
        # Without var_scaling only the EWMA vol factor applies (>= min_scale).
        assert scaled >= 0.15  # min_scale 0.5 × 0.30

    def test_cvar_within_limit_no_extra_scale(self) -> None:
        """CVaR = 0.0 within limit → cvar factor = 1.0 (no extra shrink)."""
        engine = _engine_with_var_history(-0.03, var_scaling=True, history=[0.0] * 60)
        scaled = engine._scale_budget_pct("trend", 0.30)
        # Zero variance → vol scaling falls back to the static budget.
        assert scaled == 0.30

    def test_empty_cache_fails_safe(self) -> None:
        """No cached CVaR → no extra scaling (never crashes)."""
        config = RiskConfig(cvar_limit=-0.05)
        config.dynamic_budget = DynamicBudgetConfig(enabled=True, var_scaling=True, min_samples=5)
        engine = RiskEngine(config, strategy_risk_budgets={"trend": 0.30})
        for r in [0.0] * 30:
            engine.add_return(r)
        # No check() ran → cache is stale (len -1) → fail-safe path.
        assert engine._scale_budget_pct("trend", 0.30) > 0.0
