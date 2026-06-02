"""Risk engine — multi-layer risk checks before order submission."""

from __future__ import annotations

import logging

import numpy as np

from quantflow.common.config import RiskConfig
from quantflow.common.models import Portfolio, RiskDecision, Signal

logger = logging.getLogger(__name__)


class RiskEngine:
    """Multi-layer risk check pipeline.

    Checks are run in order; the first failure short-circuits.
    """

    def __init__(self, config: RiskConfig) -> None:
        self._config = config
        self._weekly_pnl_pct: float = 0.0
        self._returns_history: list[float] = []

    def set_weekly_pnl(self, pnl_pct: float) -> None:
        """Update weekly PnL percentage (called by portfolio manager)."""
        self._weekly_pnl_pct = pnl_pct

    def add_return(self, ret: float) -> None:
        """Add a return to history for VaR calculation."""
        self._returns_history.append(ret)
        if len(self._returns_history) > 500:
            self._returns_history = self._returns_history[-500:]

    def check(self, signal: Signal, portfolio: Portfolio) -> RiskDecision:
        """Run all risk checks on a signal."""
        checks = [
            self._check_position_limit,
            self._check_portfolio_limit,
            self._check_daily_loss,
            self._check_weekly_loss,
            self._check_drawdown,
            self._check_var,
        ]
        for check_fn in checks:
            result = check_fn(signal, portfolio)
            if not result.passed:
                logger.warning("Risk check failed: %s", result.reason)
                self._record_risk_event(result.reason, "warn")
                return result
        return RiskDecision(passed=True)

    def _record_risk_event(self, event_type: str, severity: str) -> None:
        """Record risk event to Prometheus."""
        from quantflow.monitoring.metrics import RISK_EVENTS

        RISK_EVENTS.labels(event_type=event_type, severity=severity).inc()

    def _check_position_limit(self, signal: Signal, portfolio: Portfolio) -> RiskDecision:
        symbol = signal.symbol
        if symbol in portfolio.positions:
            pos = portfolio.positions[symbol]
            pos_value = abs(pos.quantity) * pos.current_price if pos.current_price > 0 else 0
            total = portfolio.total_value
            pos_pct = pos_value / total if total > 0 else 0
            if pos_pct >= self._config.position_limit_pct:
                return RiskDecision(
                    passed=False,
                    reason="position_limit",
                    details={"pct": pos_pct, "limit": self._config.position_limit_pct},
                )
        return RiskDecision(passed=True)

    def _check_portfolio_limit(self, signal: Signal, portfolio: Portfolio) -> RiskDecision:
        if len(portfolio.positions) >= self._config.max_positions:
            if signal.symbol not in portfolio.positions:
                return RiskDecision(
                    passed=False,
                    reason="max_positions",
                    details={
                        "count": len(portfolio.positions),
                        "limit": self._config.max_positions,
                    },
                )
        return RiskDecision(passed=True)

    def _check_daily_loss(self, signal: Signal, portfolio: Portfolio) -> RiskDecision:
        total_pnl = sum(p.unrealized_pnl for p in portfolio.positions.values())
        total = portfolio.total_value
        pnl_pct = total_pnl / total if total > 0 else 0
        if pnl_pct < self._config.daily_loss_limit:
            return RiskDecision(
                passed=False,
                reason="daily_loss_limit",
                details={"pnl_pct": pnl_pct, "limit": self._config.daily_loss_limit},
            )
        return RiskDecision(passed=True)

    def _check_weekly_loss(self, signal: Signal, portfolio: Portfolio) -> RiskDecision:
        if self._weekly_pnl_pct < self._config.weekly_loss_limit:
            return RiskDecision(
                passed=False,
                reason="weekly_loss_limit",
                details={"pnl_pct": self._weekly_pnl_pct, "limit": self._config.weekly_loss_limit},
            )
        return RiskDecision(passed=True)

    def _check_drawdown(self, signal: Signal, portfolio: Portfolio) -> RiskDecision:
        dd = portfolio.current_drawdown
        if dd < self._config.max_drawdown:
            return RiskDecision(
                passed=False,
                reason="max_drawdown",
                details={"drawdown": dd, "limit": self._config.max_drawdown},
            )
        return RiskDecision(passed=True)

    def _check_var(self, signal: Signal, portfolio: Portfolio) -> RiskDecision:
        """Check VaR (Value at Risk) limit."""
        if len(self._returns_history) < 30:
            return RiskDecision(passed=True)

        returns = np.array(self._returns_history)
        var_95 = np.percentile(returns, 5)
        cvar_95 = (
            returns[returns <= var_95].mean() if len(returns[returns <= var_95]) > 0 else var_95
        )

        # If CVaR exceeds 5% loss, block the signal
        if cvar_95 < -0.05:
            return RiskDecision(
                passed=False, reason="var_breach", details={"var_95": var_95, "cvar_95": cvar_95}
            )
        return RiskDecision(passed=True)

    def calculate_var(self, confidence: float = 0.95) -> float:
        """Calculate historical VaR."""
        if len(self._returns_history) < 30:
            return 0.0
        returns = np.array(self._returns_history)
        return float(np.percentile(returns, (1 - confidence) * 100))

    def calculate_cvar(self, confidence: float = 0.95) -> float:
        """Calculate CVaR (Expected Shortfall)."""
        if len(self._returns_history) < 30:
            return 0.0
        returns = np.array(self._returns_history)
        var = np.percentile(returns, (1 - confidence) * 100)
        tail = returns[returns <= var]
        return float(tail.mean()) if len(tail) > 0 else float(var)
