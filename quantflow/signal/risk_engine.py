"""Risk engine — multi-layer risk checks before order submission."""

from __future__ import annotations

import logging

import numpy as np

from quantflow.common.config import RiskConfig
from quantflow.common.models import Portfolio, RiskDecision, Signal, strategy_id_constituents

logger = logging.getLogger(__name__)


class RiskEngine:
    """Multi-layer risk check pipeline.

    Checks are run in order; the first failure short-circuits.
    """

    def __init__(
        self,
        config: RiskConfig,
        strategy_risk_budgets: dict[str, float] | None = None,
    ) -> None:
        self._config = config
        self._strategy_risk_budgets = strategy_risk_budgets or {}
        self._weekly_pnl_pct: float = 0.0
        self._returns_history: list[float] = []
        # Cache of the last-computed VaR/CVaR percentiles. _check_var runs once
        # per signal; recomputing np.percentile over the full history on every
        # signal is wasteful when the history has not changed since the last
        # bar. Invalidated by add_return (new bar) and reset() (new session).
        self._var_cache_len: int = -1
        self._var_cache_var: float = 0.0
        self._var_cache_cvar: float = 0.0

    def set_weekly_pnl(self, pnl_pct: float) -> None:
        """Update weekly PnL percentage (called by portfolio manager)."""
        self._weekly_pnl_pct = pnl_pct

    def add_return(self, ret: float) -> None:
        """Add a return to history for VaR calculation."""
        self._returns_history.append(ret)
        if len(self._returns_history) > 500:
            self._returns_history = self._returns_history[-500:]
        # History changed — invalidate the percentile cache (PERF-M3).
        self._var_cache_len = -1

    def reset(self) -> None:
        """Reset per-session state so a fresh session does not inherit the
        previous session's returns / weekly-PnL history.

        TradingSession reuses a single RiskEngine instance across runs; without
        a reset, a restarted session would gate on stale returns from the prior
        run (CORR-M2), biasing VaR and weekly-loss checks. Call at session
        start (or wherever a clean run begins).
        """
        self._returns_history.clear()
        self._weekly_pnl_pct = 0.0
        self._var_cache_len = -1

    def check(self, signal: Signal, portfolio: Portfolio) -> RiskDecision:
        """Run all risk checks on a signal."""
        checks = [
            self._check_position_limit,
            self._check_portfolio_limit,
            self._check_strategy_budget,
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

    def _check_strategy_budget(self, signal: Signal, portfolio: Portfolio) -> RiskDecision:
        """Check per-strategy risk budget allocation.

        A consolidated signal carries a compound ``strategy_id`` (e.g.
        ``"momentum_rotation,trend_following"``). Expand it and enforce each
        constituent's budget; otherwise the joined key never matches a
        single-strategy budget and the check is silently bypassed.
        """
        if not self._strategy_risk_budgets:
            return RiskDecision(passed=True)

        constituents = strategy_id_constituents(signal.strategy_id)
        # Fall back to the raw id when it isn't compound (covers single-strategy
        # signals and any non-joinable custom ids).
        budget_keys = constituents or [signal.strategy_id]
        budgeted = [k for k in budget_keys if k in self._strategy_risk_budgets]
        if not budgeted:
            return RiskDecision(passed=True)

        total_value = portfolio.total_value
        if total_value <= 0:
            return RiskDecision(passed=True)

        # Block if exposure attributed to any constituent strategy exceeds that
        # strategy's budget. A position is attributed to a constituent when its
        # strategy_id matches or is itself a compound key containing it.
        for key in budgeted:
            budget_pct = self._strategy_risk_budgets[key]
            strategy_exposure = 0.0
            for pos in portfolio.positions.values():
                pos_constituents = strategy_id_constituents(pos.strategy_id) or [pos.strategy_id]
                if key in pos_constituents:
                    pos_value = (
                        abs(pos.quantity) * pos.current_price if pos.current_price > 0 else 0
                    )
                    strategy_exposure += pos_value

            budget_limit = total_value * budget_pct
            if strategy_exposure >= budget_limit:
                return RiskDecision(
                    passed=False,
                    reason="strategy_budget",
                    details={
                        "strategy_id": key,
                        "exposure": strategy_exposure,
                        "budget": budget_limit,
                        "budget_pct": budget_pct,
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
        """Check VaR (Value at Risk) limit.

        The returns history is portfolio-level (fed by TradingSession.on_bar's
        mark-to-market of total equity), so this gate — and the per-strategy
        _check_strategy_budget — operate at different granularities by design
        (ARCH-L2): a signal on symbol A may be blocked by portfolio VaR driven
        primarily by symbol B's losses. This is intentional (portfolio VaR
        should gate all signals); per-strategy isolation is _check_strategy_budget's
        job, not this gate's.
        """
        if len(self._returns_history) < 30:
            return RiskDecision(passed=True)

        # Percentile recompute is O(n log n); cache it keyed on history length
        # so multiple signals within the same bar share one computation (PERF-M3).
        # add_return invalidates the cache when a new bar arrives.
        if len(self._returns_history) != self._var_cache_len:
            returns = np.array(self._returns_history)
            var_pct = (1 - self._config.var_confidence) * 100
            var_95 = np.percentile(returns, var_pct)
            tail = returns[returns <= var_95]
            cvar_95 = float(tail.mean()) if len(tail) > 0 else float(var_95)
            self._var_cache_len = len(self._returns_history)
            self._var_cache_var = float(var_95)
            self._var_cache_cvar = cvar_95
        else:
            cvar_95 = self._var_cache_cvar

        # If CVaR exceeds the configured loss threshold, block the signal.
        if cvar_95 < self._config.cvar_limit:
            return RiskDecision(
                passed=False,
                reason="var_breach",
                details={"var_95": self._var_cache_var, "cvar_95": cvar_95},
            )
        return RiskDecision(passed=True)

    def calculate_var(self, confidence: float | None = None) -> float:
        """Calculate historical VaR at the configured (or override) confidence."""
        if len(self._returns_history) < 30:
            return 0.0
        c = self._config.var_confidence if confidence is None else confidence
        returns = np.array(self._returns_history)
        return float(np.percentile(returns, (1 - c) * 100))

    def calculate_cvar(self, confidence: float | None = None) -> float:
        """Calculate CVaR (Expected Shortfall) at the configured (or override) confidence."""
        if len(self._returns_history) < 30:
            return 0.0
        c = self._config.var_confidence if confidence is None else confidence
        returns = np.array(self._returns_history)
        var = np.percentile(returns, (1 - c) * 100)
        tail = returns[returns <= var]
        return float(tail.mean()) if len(tail) > 0 else float(var)
