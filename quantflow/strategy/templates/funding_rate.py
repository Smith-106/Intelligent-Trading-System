"""Funding rate strategy — crypto-specific signal using funding rate extremes + open interest."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyBase, StrategyContext

logger = logging.getLogger(__name__)


class FundingRateStrategy(StrategyBase):
    """Funding rate mean-reversion strategy.

    Crypto perpetual swaps charge a funding rate every 8h.
    Extreme rates signal overcrowded positions → mean reversion.

    Entry:
    - Long when funding_rate < -threshold (shorts overcrowded → price likely up)
    - Short when funding_rate > +threshold (longs overcrowded → price likely down)
    - Open interest confirmation: OI change aligns with the crowd direction

    Exit:
    - Funding rate returns to neutral zone (between ±exit_threshold)
    - OI reversal signal
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(name="funding_rate", params=params)
        p = self._params
        self._entry_threshold = p.get("entry_threshold", 0.001)
        self._exit_threshold = p.get("exit_threshold", 0.0003)
        self._oi_lookback = p.get("oi_lookback", 3)
        self._oi_change_threshold = p.get("oi_change_threshold", 0.05)
        self._rate_ema_period = p.get("rate_ema_period", 8)
        self._cooldown_bars = p.get("cooldown_bars", 6)

        self._bars: list[Bar] = []
        self._funding_rates: list[float] = []
        self._open_interests: list[float] = []
        self._cooldown_counter = 0
        self._max_bars = 200

    def on_init(self, ctx: StrategyContext) -> None:
        ctx.params = self._params

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        self._bars.append(bar)
        if len(self._bars) > self._max_bars:
            self._bars = self._bars[-self._max_bars:]

        if self._cooldown_counter > 0:
            self._cooldown_counter -= 1
            return

        min_bars = max(self._rate_ema_period * 2, self._oi_lookback + 1)
        if len(self._bars) < min_bars or len(self._funding_rates) < min_bars:
            return

        df = self._build_signal_df()
        if df.empty:
            return

        entries, exits = self.generate_signals(df)
        if entries.empty:
            return

        last_idx = len(entries) - 1
        symbol = bar.symbol

        if entries.iloc[last_idx]:
            rate = self._funding_rates[-1] if self._funding_rates else 0.0
            direction = Direction.LONG if rate < -self._entry_threshold else Direction.SHORT
            ctx.emit_signal(symbol, direction, strength=0.7, price=bar.close,
                            strategy_id=self.name)
            self._cooldown_counter = self._cooldown_bars
        elif exits.iloc[last_idx]:
            ctx.emit_signal(symbol, Direction.FLAT, strength=0.5, price=bar.close,
                            strategy_id=self.name)

    def update_funding_rate(self, rate: float) -> None:
        """Feed a new funding rate observation (called externally by data layer)."""
        self._funding_rates.append(rate)
        if len(self._funding_rates) > self._max_bars:
            self._funding_rates = self._funding_rates[-self._max_bars:]

    def update_open_interest(self, oi: float) -> None:
        """Feed a new open interest observation (called externally by data layer)."""
        self._open_interests.append(oi)
        if len(self._open_interests) > self._max_bars:
            self._open_interests = self._open_interests[-self._max_bars:]

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        min_bars = max(self._rate_ema_period * 2, self._oi_lookback + 1)
        if len(df) < min_bars:
            empty = pd.Series(False, index=df.index)
            return empty, empty

        funding_rate = df.get("funding_rate", pd.Series(0.0, index=df.index))
        open_interest = df.get("open_interest", pd.Series(0.0, index=df.index))

        # Rate EMA for smoothing
        rate_ema = funding_rate.ewm(span=self._rate_ema_period).mean()

        # Extreme funding rate signals
        long_signal = rate_ema < -self._entry_threshold  # shorts crowded → go long
        short_signal = rate_ema > self._entry_threshold   # longs crowded → go short

        # Open interest confirmation: OI increasing in crowded direction
        oi_change = open_interest.pct_change(self._oi_lookback)
        oi_rising = oi_change > self._oi_change_threshold
        oi_falling = oi_change < -self._oi_change_threshold

        long_entry = long_signal & oi_rising
        short_entry = short_signal & oi_rising
        entries = long_entry | short_entry

        # Exit: rate returns to neutral
        neutral_zone = rate_ema.abs() < self._exit_threshold
        # Or OI reversal
        oi_reversal = (long_signal & oi_falling) | (short_signal & oi_falling)
        exits = neutral_zone | oi_reversal

        return entries.fillna(False), exits.fillna(False)

    def _build_signal_df(self) -> pd.DataFrame:
        if not self._bars:
            return pd.DataFrame()
        n = min(len(self._bars), len(self._funding_rates), len(self._open_interests))
        if n == 0:
            return pd.DataFrame()
        data = {
            "timestamp": [b.timestamp for b in self._bars[:n]],
            "close": [b.close for b in self._bars[:n]],
            "funding_rate": self._funding_rates[:n],
            "open_interest": self._open_interests[:n],
        }
        return pd.DataFrame(data)

    def get_required_indicators(self) -> list[dict[str, Any]]:
        return [
            {"name": "funding_rate", "params": {"ema_period": self._rate_ema_period}},
            {"name": "open_interest", "params": {"lookback": self._oi_lookback}},
        ]
