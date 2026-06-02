"""Pure pandas/numpy vectorized backtest engine.

Replaces VectorBT dependency which is incompatible with Python 3.14+ (requires numba).
"""

from __future__ import annotations

import logging
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

    Simulates a simple long-only portfolio from boolean entry/exit signals.
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
    ) -> BacktestResult:
        """Run vectorized backtest with entry/exit signals."""
        entries = entries.reindex(close.index).fillna(False).astype(bool)
        exits = exits.reindex(close.index).fillna(False).astype(bool)

        n = len(close)
        equity = np.full(n, initial_capital, dtype=float)
        in_position = False
        entry_price = 0.0
        trades: list[tuple[float, float]] = []  # (entry_price, exit_price)

        for i in range(1, n):
            prev_idx = i - 1
            if not in_position and entries.iloc[prev_idx]:
                in_position = True
                entry_price = close.iloc[i] * (1 + fee)
                equity[i] = equity[prev_idx]
            elif in_position and exits.iloc[prev_idx]:
                exit_price = close.iloc[i] * (1 - fee)
                trades.append((entry_price, exit_price))
                ret = (exit_price - entry_price) / entry_price
                equity[i] = equity[prev_idx] * (1 + ret)
                in_position = False
                entry_price = 0.0
            else:
                equity[i] = equity[prev_idx]

        # Close any open position at last bar
        if in_position and n > 0:
            exit_price = close.iloc[-1] * (1 - fee)
            trades.append((entry_price, exit_price))
            ret = (exit_price - entry_price) / entry_price
            equity[-1] = equity[-1] * (1 + ret)

        equity_series = pd.Series(equity, index=close.index)
        returns = equity_series.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)

        # Drawdown
        peak = equity_series.cummax()
        dd = (equity_series - peak) / peak
        max_dd = float(dd.min())

        # Trade stats
        num_trades = len(trades)
        trade_pnls = [
            (exit_price - entry_price) / entry_price for entry_price, exit_price in trades
        ] if num_trades > 0 else []
        wins = [p for p in trade_pnls if p > 0]
        losses = [p for p in trade_pnls if p < 0]
        win_rate = len(wins) / num_trades if num_trades > 0 else 0.0
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 1.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Ratios
        total_return = (equity[-1] / initial_capital) - 1
        num_days = max(n, 1)
        if total_return <= -1:
            annual_return = -1.0
        elif not np.isfinite(total_return):
            annual_return = float("inf")
        else:
            log_growth = np.log1p(total_return) * (365 / num_days)
            annual_return = float(np.expm1(log_growth)) if log_growth < 700 else float("inf")
        sharpe = self._calc_sharpe(returns)
        sortino = self._calc_sortino(returns)
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
    def _calc_sharpe(returns: pd.Series, risk_free: float = 0.0) -> float:
        r = returns.replace([np.inf, -np.inf], np.nan).dropna()
        if len(r) < 2 or r.std() == 0:
            return 0.0
        return float((r.mean() - risk_free / 252) / r.std() * np.sqrt(252))

    @staticmethod
    def _calc_sortino(returns: pd.Series, risk_free: float = 0.0) -> float:
        r = returns.replace([np.inf, -np.inf], np.nan).dropna()
        if len(r) < 2:
            return 0.0
        downside = r[r < risk_free / 252]
        if len(downside) == 0 or downside.std() == 0:
            return 0.0
        return float((r.mean() - risk_free / 252) / downside.std() * np.sqrt(252))
