"""Risk engine — multi-layer risk checks before order submission."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable

import numpy as np

from quantflow.common.config import RiskConfig
from quantflow.common.models import Portfolio, RiskDecision, Signal, strategy_id_constituents
from quantflow.common.monitoring_sink import MonitoringSink, NullMonitoringSink

logger = logging.getLogger(__name__)


class RiskEngine:
    """Multi-layer risk check pipeline.

    Checks are run in order; the first failure short-circuits.
    """

    def __init__(
        self,
        config: RiskConfig,
        strategy_risk_budgets: dict[str, float] | None = None,
        monitoring_sink: MonitoringSink | None = None,
    ) -> None:
        self._config = config
        self._strategy_risk_budgets = strategy_risk_budgets or {}
        # L4→L6 seam (ISS-20260724-044): RiskEngine depends on the MonitoringSink
        # Protocol only. The concrete sink (DefaultMonitoringSink from L6) is
        # injected by TradingSession; defaulting to Null keeps tests/backtest
        # zero-observability — and removes the in-function `RISK_EVENTS` import
        # that hid the L6 coupling from top-level grep (audit-evasion).
        self._sink: MonitoringSink = monitoring_sink or NullMonitoringSink()
        self._weekly_pnl_pct: float = 0.0
        # deque(maxlen=500) makes add_return O(1) with automatic eviction,
        # replacing the list + [-500:] slice (O(n) copy each overflow).
        # (odyssey-improve PERF-L5)
        self._returns_history: deque[float] = deque(maxlen=500)
        # Cache of the last-computed VaR/CVaR percentiles. _check_var runs once
        # per signal; recomputing np.percentile over the full history on every
        # signal is wasteful when the history has not changed since the last
        # bar. Invalidated by add_return (new bar) and reset() (new session).
        self._var_cache_len: int = -1
        self._var_cache_var: float = 0.0
        self._var_cache_cvar: float = 0.0
        # Build the check tuple once (odyssey-improve PERF-L1): previously
        # check() allocated a fresh 7-element list of bound methods per signal.
        # A tuple built in __init__ is iterated with zero per-call allocation.
        self._checks: tuple[Callable[[Signal, Portfolio], RiskDecision], ...] = (
            self._check_position_limit,
            self._check_portfolio_limit,
            self._check_strategy_budget,
            self._check_daily_loss,
            self._check_weekly_loss,
            self._check_drawdown,
            self._check_var,
        )

    def set_weekly_pnl(self, pnl_pct: float) -> None:
        """Update weekly PnL percentage (called by portfolio manager)."""
        self._weekly_pnl_pct = pnl_pct

    def add_return(self, ret: float) -> None:
        """Add a return to history for VaR calculation."""
        self._returns_history.append(ret)  # deque(maxlen=500) evicts automatically
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
        for check_fn in self._checks:
            result = check_fn(signal, portfolio)
            if not result.passed:
                logger.warning("Risk check failed: %s", result.reason)
                self._record_risk_event(result.reason, "warn")
                return result
        return RiskDecision(passed=True)

    def _record_risk_event(self, event_type: str, severity: str) -> None:
        """Record risk event via the injected sink (ISS-20260724-044).

        Previously an in-function ``from quantflow.monitoring.metrics import
        RISK_EVENTS`` — an audit-evasion lazy-import that hid the L4→L6
        coupling from top-level grep. Now routes through the MonitoringSink
        Protocol (default Null = no-op).
        """
        self._sink.record_risk_event(event_type, severity)

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

        # Single-pass exposure attribution: each position's constituents are
        # computed once (strategy_id_constituents is a string split), then
        # exposure is accumulated per constituent. The prior nested loop
        # recomputed every position's constituents for each budgeted key —
        # O(budgeted × positions × split) per signal; this is O(positions ×
        # split + budgeted). Positions whose value can't be attributed to any
        # budgeted key are skipped.
        budgeted_set = set(budgeted)
        exposure_by_key: dict[str, float] = {key: 0.0 for key in budgeted}
        for pos in portfolio.positions.values():
            if pos.current_price <= 0:
                continue
            pos_constituents = strategy_id_constituents(pos.strategy_id) or [pos.strategy_id]
            if not any(c in budgeted_set for c in pos_constituents):
                continue
            pos_value = abs(pos.quantity) * pos.current_price
            for c in pos_constituents:
                if c in budgeted_set:
                    exposure_by_key[c] += pos_value

        for key in budgeted:
            budget_pct = self._strategy_risk_budgets[key]
            strategy_exposure = exposure_by_key[key]
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
