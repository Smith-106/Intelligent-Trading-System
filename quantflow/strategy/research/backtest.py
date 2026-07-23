"""Pure pandas/numpy vectorized backtest engine.

Replaces VectorBT dependency which is incompatible with Python 3.14+ (requires numba).
"""

from __future__ import annotations

import logging
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Standardized backtest result."""

    strategy_id: str
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_return: float
    annual_return: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    num_trades: int
    equity_curve: pd.Series = field(default_factory=pd.Series)
    drawdown_curve: pd.Series = field(default_factory=pd.Series)
    # Per-closed-trade realized returns (fractions), in chronological order.
    # Empty list when no trades closed. Used by the Monte Carlo path-level
    # stress test (validation/monte_carlo.py) to permute trade ordering.
    trade_returns: list[float] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"=== Backtest: {self.strategy_id} / {self.symbol} ===\n"
            f"Period:     {self.start_date} -> {self.end_date}\n"
            f"Capital:    {self.initial_capital:,.0f} -> {self.final_capital:,.0f}\n"
            f"Return:     {self.total_return:.2%} (annual: {self.annual_return:.2%})\n"
            f"Sharpe:     {self.sharpe_ratio:.3f}\n"
            f"Sortino:    {self.sortino_ratio:.3f}\n"
            f"Calmar:     {self.calmar_ratio:.3f}\n"
            f"Max DD:     {self.max_drawdown:.2%}\n"
            f"Win Rate:   {self.win_rate:.2%}\n"
            f"Profit Fac: {self.profit_factor:.3f}\n"
            f"Trades:     {self.num_trades}"
        )


class BacktestEngine:
    """Vectorized backtest engine using pure pandas/numpy.

    Supports both LONG and SHORT positions via the ``direction`` parameter.
    Positions are whole-bar: enter at next-bar open after signal, exit at
    next-bar open after exit signal. Fees are applied on each entry/exit.
    """

    def run_backtest(
        self,
        close: pd.Series,
        entries: pd.Series,
        exits: pd.Series,
        initial_capital: float = 10000.0,
        fee: float = 0.001,
        strategy_id: str = "strategy",
        symbol: str = "BTC/USDT",
        direction: pd.Series | int = 1,
    ) -> BacktestResult:
        """Run vectorized backtest with entry/exit signals.

        Parameters
        ----------
        close : pd.Series
            Close prices.
        entries : pd.Series
            Boolean entry signals.
        exits : pd.Series
            Boolean exit signals.
        direction : pd.Series | int
            Trade direction: 1 for LONG, -1 for SHORT. Can be a Series
            aligned to ``close`` for per-bar direction, or an int for
            uniform direction. Default is 1 (LONG, backward compatible).
        """
        entries = entries.reindex(close.index).fillna(False).astype(bool)
        exits = exits.reindex(close.index).fillna(False).astype(bool)

        n = len(close)
        if n == 0:
            empty_curve = pd.Series(dtype=float)
            return BacktestResult(
                strategy_id=strategy_id,
                symbol=symbol,
                start_date="",
                end_date="",
                initial_capital=initial_capital,
                final_capital=initial_capital,
                total_return=0.0,
                annual_return=0.0,
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                calmar_ratio=0.0,
                max_drawdown=0.0,
                win_rate=0.0,
                profit_factor=0.0,
                num_trades=0,
                equity_curve=empty_curve,
                drawdown_curve=empty_curve,
            )

        # Resolve direction: int → uniform array, or align existing Series
        if isinstance(direction, int):
            dir_values = np.full(n, direction, dtype=float)
        else:
            dir_series = direction.reindex(close.index).fillna(1).astype(float)
            dir_values = dir_series.to_numpy(dtype=float, copy=False)

        close_values = close.to_numpy(dtype=float, copy=False)
        entry_values = entries.to_numpy(dtype=bool, copy=False)
        exit_values = exits.to_numpy(dtype=bool, copy=False)
        equity = np.full(n, initial_capital, dtype=float)
        in_position = False
        entry_price = 0.0
        entry_dir = 1.0  # 1=LONG, -1=SHORT
        trades: list[tuple[float, float, float]] = []  # (entry_price, exit_price, direction)

        for i in range(1, n):
            prev_idx = i - 1
            if not in_position and entry_values[prev_idx]:
                in_position = True
                entry_dir = dir_values[prev_idx]
                if entry_dir > 0:  # LONG
                    entry_price = close_values[i] * (1 + fee)
                else:  # SHORT
                    entry_price = close_values[i] * (1 - fee)
                equity[i] = equity[prev_idx]
            elif in_position and exit_values[prev_idx]:
                if entry_dir > 0:  # LONG exit
                    exit_price = close_values[i] * (1 - fee)
                    ret = (exit_price - entry_price) / entry_price
                else:  # SHORT exit
                    exit_price = close_values[i] * (1 + fee)
                    ret = (entry_price - exit_price) / entry_price
                trades.append((entry_price, exit_price, entry_dir))
                equity[i] = equity[prev_idx] * (1 + ret)
                in_position = False
                entry_price = 0.0
                entry_dir = 1.0
            else:
                equity[i] = equity[prev_idx]

        # Close any open position at last bar
        if in_position and n > 0:
            if entry_dir > 0:  # LONG exit
                exit_price = close_values[-1] * (1 - fee)
                ret = (exit_price - entry_price) / entry_price
            else:  # SHORT exit
                exit_price = close_values[-1] * (1 + fee)
                ret = (entry_price - exit_price) / entry_price
            trades.append((entry_price, exit_price, entry_dir))
            equity[-1] = equity[-1] * (1 + ret)

        equity_series = pd.Series(equity, index=close.index)
        returns = equity_series.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)

        # Drawdown
        peak = equity_series.cummax()
        dd = (equity_series - peak) / peak
        max_dd = float(dd.min())

        # Trade stats — direction-aware P&L
        num_trades = len(trades)
        trade_pnls = []
        for ep, xp, d in trades:
            if d > 0:  # LONG
                trade_pnls.append((xp - ep) / ep)
            else:  # SHORT
                trade_pnls.append((ep - xp) / ep)
        wins = [p for p in trade_pnls if p > 0]
        losses = [p for p in trade_pnls if p < 0]
        win_rate = len(wins) / num_trades if num_trades > 0 else 0.0
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 1.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Ratios
        total_return = (equity[-1] / initial_capital) - 1
        periods_per_year = self._periods_per_year(close.index)
        # Span of the backtest in years, derived from the bar frequency rather
        # than assuming daily bars (crypto trades intraday; hourly bars would
        # otherwise understate annualization by ~24x).
        bars_per_year = periods_per_year
        n_years = n / bars_per_year if bars_per_year > 0 else 1.0
        if total_return <= -1:
            annual_return = -1.0
        elif not np.isfinite(total_return):
            annual_return = float("inf")
        else:
            log_growth = np.log1p(total_return) / max(n_years, 1e-12)
            annual_return = float(np.expm1(log_growth)) if log_growth < 700 else float("inf")
        sharpe = self._calc_sharpe(returns, periods_per_year=periods_per_year)
        sortino = self._calc_sortino(returns, periods_per_year=periods_per_year)
        calmar = abs(annual_return / max_dd) if max_dd != 0 else 0.0

        return BacktestResult(
            strategy_id=strategy_id,
            symbol=symbol,
            start_date=str(close.index[0]) if n > 0 else "",
            end_date=str(close.index[-1]) if n > 0 else "",
            initial_capital=initial_capital,
            final_capital=float(equity[-1]),
            total_return=total_return,
            annual_return=annual_return,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            max_drawdown=max_dd,
            win_rate=win_rate,
            profit_factor=profit_factor,
            num_trades=num_trades,
            equity_curve=equity_series,
            drawdown_curve=dd,
            trade_returns=trade_pnls,
        )

    def parameter_sweep(
        self,
        close: pd.Series,
        param_combos: list[dict[str, Any]],
        signal_fn: Callable[..., tuple[pd.Series, pd.Series]],
        initial_capital: float = 10000.0,
        fee: float = 0.001,
    ) -> list[BacktestResult]:
        """Run backtest across multiple parameter combinations."""
        results = []
        for params in param_combos:
            entries, exits = signal_fn(close, **params)
            result = self.run_backtest(
                close,
                entries,
                exits,
                initial_capital=initial_capital,
                fee=fee,
                strategy_id=f"sweep_{hash(frozenset(params.items()))}",
            )
            results.append(result)
        return sorted(results, key=lambda r: r.sharpe_ratio, reverse=True)

    @staticmethod
    def _periods_per_year(index: pd.Index) -> float:
        """Infer the number of bars per year from the index frequency.

        Falls back to 365 (daily) when the frequency cannot be inferred, so
        annualization is correct for the common daily case and improved for
        intraday crypto bars (hourly -> 8760, etc.) instead of always
        assuming daily.
        """
        inferred = None
        try:
            inferred = pd.infer_freq(index)
        except (TypeError, ValueError):
            inferred = None
        if inferred:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    offset = pd.tseries.frequencies.to_offset(inferred)
                if offset is not None and offset.nanos > 0:
                    return float(365 * 24 * 3600 * 1_000_000_000 / offset.nanos)
            except (TypeError, ValueError, AttributeError):
                pass
        # Try median timedelta between consecutive bars.
        try:
            if len(index) >= 2:
                deltas = pd.Series(index).diff().dropna()
                if len(deltas) > 0:
                    median_delta = deltas.median()
                    if pd.notna(median_delta) and median_delta > pd.Timedelta(0):
                        return float(pd.Timedelta(days=365) / median_delta)
        except (TypeError, ValueError):
            pass
        # Fallback (odyssey-review CORR finding): falling back to 365 (daily)
        # here understates annualization for intraday bars by ~24x for hourly
        # data, silently inflating annualized Sharpe/return. Warn so an
        # operator sees the cadence could not be inferred — previously this
        # path fired with no log at all.
        logger.warning(
            "Could not infer bar frequency from index (len=%d, type=%s); "
            "defaulting periods_per_year=365 (daily). If bars are intraday, "
            "annualized Sharpe/return will be understated.",
            len(index),
            type(index).__name__,
        )
        return 365.0

    @staticmethod
    def _calc_sharpe(
        returns: pd.Series, risk_free: float = 0.0, periods_per_year: float = 365.0
    ) -> float:
        r = returns.replace([np.inf, -np.inf], np.nan).dropna()
        if len(r) < 2 or r.std() == 0:
            return 0.0
        # Annualize using the inferred bar frequency rather than a hardcoded
        # 252 (daily equities) which is wrong for intraday crypto bars.
        ann = max(periods_per_year, 1.0)
        return float((r.mean() - risk_free / ann) / r.std() * np.sqrt(ann))

    @staticmethod
    def _calc_sortino(
        returns: pd.Series, risk_free: float = 0.0, periods_per_year: float = 365.0
    ) -> float:
        r = returns.replace([np.inf, -np.inf], np.nan).dropna()
        if len(r) < 2:
            return 0.0
        ann = max(periods_per_year, 1.0)
        downside = r[r < risk_free / ann]
        if len(downside) == 0 or downside.std() == 0:
            return 0.0
        return float((r.mean() - risk_free / ann) / downside.std() * np.sqrt(ann))
