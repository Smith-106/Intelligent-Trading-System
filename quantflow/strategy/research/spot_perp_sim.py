"""Spot-perp pair P&L simulation (ISS-20260804-003 real-data validation).

Models the market-neutral funding-harvest pair of
:class:`quantflow.strategy.templates.spot_perp_arb.SpotPerpArbStrategy`:

* perp leg with direction ``d`` (from the strategy's perp entries: +1 long
  perp, -1 short perp)
* spot leg mirrored (``-d``) — the pair is direction-neutral by design
* funding income on the perp leg: longs pay shorts when funding > 0, so the
  perp leg accrues ``-d * funding_rate`` at each settlement bar
* entry/exit fees applied to BOTH legs at the open of the bar after the
  signal (whole-bar semantics, mirroring BacktestEngine)

``generate_signals`` needs ``funding_rate`` + ``open_interest`` columns;
the simulator additionally needs ``perp_close``/``perp_open`` and
``spot_close``/``spot_open`` plus the ``funding_settle`` settlement mask
(1 at actual funding settlement bars).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from quantflow.strategy.research.backtest import BacktestEngine
from quantflow.strategy.templates.spot_perp_arb import SpotPerpArbStrategy

logger = logging.getLogger(__name__)


@dataclass
class SpotPerpPairResult:
    """Standardized pair backtest result."""

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
    funding_income: float  # cumulative funding received (fraction of notional)
    spread_pnl: float  # cumulative spread-drift P&L (fraction of notional)
    returns: pd.Series = field(default_factory=pd.Series)
    equity_curve: pd.Series = field(default_factory=pd.Series)
    trade_returns: list[float] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"=== SpotPerpPair: {self.strategy_id} / {self.symbol} ===\n"
            f"Period:     {self.start_date} -> {self.end_date}\n"
            f"Capital:    {self.initial_capital:,.0f} -> {self.final_capital:,.0f}\n"
            f"Return:     {self.total_return:.2%} (annual: {self.annual_return:.2%})\n"
            f"Sharpe:     {self.sharpe_ratio:.3f}  Sortino: {self.sortino_ratio:.3f}\n"
            f"Max DD:     {self.max_drawdown:.2%}  Calmar: {self.calmar_ratio:.3f}\n"
            f"Win Rate:   {self.win_rate:.2%}  Profit Fac: {self.profit_factor:.3f}\n"
            f"Trades:     {self.num_trades}\n"
            f"Funding:    {self.funding_income:+.4%}  Spread P&L: {self.spread_pnl:+.4%}"
        )


class SpotPerpPairSimulator:
    """Vectorized-ish pair P&L simulator for the spot-perp arb prototype.

    Args:
        params: strategy params (entry_threshold / exit_threshold /
            oi_lookback / oi_change_threshold), see SpotPerpArbStrategy.
        fee_per_leg: fee applied to EACH leg at entry and exit (round trip
            touches 2 legs x 2 sides = 4 x fee_per_leg).
        initial_capital: starting equity.
    """

    def __init__(
        self,
        params: dict[str, Any] | None = None,
        fee_per_leg: float = 0.0005,
        initial_capital: float = 10_000.0,
    ) -> None:
        self._params = params
        self._fee = fee_per_leg
        self._capital = initial_capital

    def run(self, df: pd.DataFrame) -> SpotPerpPairResult:
        """Simulate the pair over an hourly feature frame."""
        required = {"spot_close", "perp_close", "funding_rate", "funding_settle"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Missing columns: {sorted(missing)}")

        strategy = SpotPerpArbStrategy(params=self._params)
        entries, exits = strategy.generate_signals(df)

        spot_c = df["spot_close"].astype(float)
        perp_c = df["perp_close"].astype(float)
        funding = df["funding_rate"].astype(float)
        settle = df["funding_settle"].fillna(0).astype(int)
        n = len(df)

        spot_ret = (spot_c / spot_c.shift(1) - 1.0).fillna(0.0).to_numpy()
        perp_ret = (perp_c / perp_c.shift(1) - 1.0).fillna(0.0).to_numpy()
        f_rate = funding.fillna(0.0).to_numpy()
        settle_arr = settle.to_numpy()
        entry_sig = entries.reindex(df.index).fillna(0).astype(int).to_numpy()
        exit_sig = exits.reindex(df.index).fillna(0).astype(int).to_numpy()

        bar_returns = np.zeros(n, dtype=float)
        in_position = False
        d = 0.0
        funding_total = 0.0
        spread_total = 0.0

        for i in range(1, n):
            if not in_position and entry_sig[i - 1] != 0:
                # Whole-bar: enter at bar i open, fee on both legs.
                d = float(entry_sig[i - 1])
                in_position = True
                bar_returns[i] = -2.0 * self._fee
            elif in_position and exit_sig[i - 1] != 0:
                bar_returns[i] += -2.0 * self._fee  # exit both legs at open
                in_position = False
                d = 0.0
            if in_position:
                spread_ret = perp_ret[i] - spot_ret[i]
                r = d * spread_ret
                spread_total += r
                bar_returns[i] += r
                if settle_arr[i]:
                    f_inc = -d * f_rate[i]
                    funding_total += f_inc
                    bar_returns[i] += f_inc

        # Close any open position at the last bar (mark-to-market at close).
        if in_position and n > 0:
            spread_ret = perp_ret[n - 1] - spot_ret[n - 1]
            r = d * spread_ret
            spread_total += r
            bar_returns[n - 1] += r - 2.0 * self._fee
            if settle_arr[n - 1]:
                f_inc = -d * f_rate[n - 1]
                funding_total += f_inc
                bar_returns[n - 1] += f_inc

        returns = pd.Series(bar_returns, index=df.index)
        equity = self._capital * (1.0 + returns).cumprod()
        final_capital = float(equity.iloc[-1]) if n else float(self._capital)
        total_return = final_capital / self._capital - 1.0

        trade_returns = self._extract_trade_returns(entry_sig, exit_sig, returns)
        n_trades = len(trade_returns)

        wins = [t for t in trade_returns if t > 0]
        losses = [t for t in trade_returns if t < 0]
        win_rate = len(wins) / n_trades if n_trades else 0.0
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 1.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        periods_per_year = BacktestEngine._periods_per_year(df.index)
        sharpe = BacktestEngine._calc_sharpe(returns, periods_per_year=periods_per_year)
        sortino = BacktestEngine._calc_sortino(returns, periods_per_year=periods_per_year)

        peak = equity.cummax()
        dd = (equity - peak) / peak
        max_dd = float(dd.min()) if n else 0.0
        n_years = n / periods_per_year if periods_per_year > 0 else 1.0
        if total_return <= -1:
            annual_return = -1.0
        elif n_years <= 0 or not np.isfinite(total_return):
            annual_return = float("inf") if np.isfinite(total_return) else 0.0
        else:
            annual_return = float(np.expm1(np.log1p(total_return) / n_years))
        calmar = abs(annual_return / max_dd) if max_dd != 0 else 0.0

        return SpotPerpPairResult(
            strategy_id="spot_perp_arb",
            symbol="BTC/USDT:USDT + BTC/USDT",
            start_date=str(df.index[0]),
            end_date=str(df.index[-1]),
            initial_capital=self._capital,
            final_capital=final_capital,
            total_return=total_return,
            annual_return=annual_return,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            max_drawdown=max_dd,
            win_rate=win_rate,
            profit_factor=profit_factor,
            num_trades=n_trades,
            funding_income=funding_total,
            spread_pnl=spread_total,
            returns=returns,
            equity_curve=equity,
            trade_returns=trade_returns,
        )

    @staticmethod
    def _extract_trade_returns(
        entry_sig: np.ndarray, exit_sig: np.ndarray, returns: pd.Series
    ) -> list[float]:
        """Per-position realized returns (entry-bar .. exit-bar inclusive)."""
        trades: list[float] = []
        start = -1
        for i in range(len(returns)):
            if start < 0 and i > 0 and entry_sig[i - 1] != 0:
                start = i
            if start >= 0 and (exit_sig[i - 1] != 0 or i == len(returns) - 1):
                trades.append(float(returns.iloc[start : i + 1].sum()))
                start = -1
        return trades
