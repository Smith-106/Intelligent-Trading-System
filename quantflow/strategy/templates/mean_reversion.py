"""Mean reversion strategy: RSI + Bollinger Band + volume confirmation."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyBase, StrategyContext
from quantflow.strategy.templates._runtime import (
    closes,
    profit_target_exit,
    rolling_mean_at,
    rolling_std_at,
    simple_rsi_last,
    volumes,
)

logger = logging.getLogger(__name__)


class MeanReversionStrategy(StrategyBase):
    """Mean reversion strategy using RSI + Bollinger Bands."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(name="mean_reversion", params=params)
        self.required_regime = "mean_reversion"
        p = self._params
        self._rsi_period = p.get("rsi_period", 14)
        self._rsi_oversold = p.get("rsi_oversold", 30)
        self._rsi_overbought = p.get("rsi_overbought", 70)
        self._bb_period = p.get("bb_period", 20)
        self._bb_std = p.get("bb_std", 2.0)
        self._volume_period = p.get("volume_period", 20)
        self._volume_threshold = p.get("volume_threshold", 1.2)
        self._exit_rsi_overbought = p.get("exit_rsi_overbought", 60)
        self._exit_rsi_oversold = p.get("exit_rsi_oversold", 40)
        self._min_conditions: int = p.get("min_conditions", 2)
        self._profit_take_pct: float = p.get("take_profit_pct", p.get("profit_take_pct", 0.03))
        self._max_holding_bars: int = p.get("max_holding_bars", 20)
        self._stop_loss_pct: float = p.get("stop_loss_pct", 0.0)

        self._bars: list[Bar] = []
        self._close_values: list[float] = []
        self._volume_values: list[float] = []
        self._max_bars = max(self._rsi_period, self._bb_period, self._volume_period) + 50
        # Position tracking for on_bar exit mechanisms
        self._in_position: bool = False
        self._entry_direction: Direction | None = None
        self._entry_price: float = 0.0
        self._bars_since_entry: int = 0
        self._last_entry_conditions: int = 0

    def on_init(self, ctx: StrategyContext) -> None:
        ctx.params = self._params

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        """Event-driven bar handler using an incremental latest-row path."""
        self._bars.append(bar)
        self._close_values.append(bar.close)
        self._volume_values.append(bar.volume)
        if len(self._bars) > self._max_bars:
            self._bars = self._bars[-self._max_bars :]
            self._close_values = self._close_values[-self._max_bars :]
            self._volume_values = self._volume_values[-self._max_bars :]

        if len(self._bars) < self._bb_period:
            return

        entry_direction, exit_ = self._latest_signal()
        if entry_direction is not None and not self._in_position:
            conditions_met = self._last_entry_conditions
            strength = min(0.4 + 0.25 * conditions_met, 0.9)
            ctx.emit_signal(
                bar.symbol,
                entry_direction,
                strength=strength,
                price=bar.close,
                strategy_id=self.name,
            )
            self._in_position = True
            self._entry_direction = entry_direction
            self._entry_price = bar.close
            self._bars_since_entry = 0
        elif exit_ and self._in_position:
            ctx.emit_signal(
                bar.symbol,
                Direction.FLAT,
                strength=0.3,
                price=bar.close,
                strategy_id=self.name,
            )
            self._in_position = False

        # on_bar exit mechanisms: profit target + max holding
        self._check_position_exits(ctx, bar)

    def _latest_signal(self) -> tuple[Direction | None, bool]:
        """Compute the latest event-mode signal without rebuilding a DataFrame."""
        close_values, volume_values = self._runtime_values()
        last_idx = len(close_values) - 1

        rsi = simple_rsi_last(close_values, self._rsi_period)
        bb_middle = rolling_mean_at(close_values, last_idx, self._bb_period)
        bb_std = rolling_std_at(close_values, last_idx, self._bb_period)
        volume_ma = rolling_mean_at(volume_values, last_idx, self._volume_period)
        if rsi is None or bb_middle is None or bb_std is None or volume_ma is None:
            return None, False

        close = close_values[-1]
        bb_upper = bb_middle + self._bb_std * bb_std
        bb_lower = bb_middle - self._bb_std * bb_std
        vol_ok = volume_values[-1] > volume_ma * self._volume_threshold

        long_count = int(vol_ok) + int(rsi < self._rsi_oversold) + int(close < bb_lower)
        short_count = int(vol_ok) + int(rsi > self._rsi_overbought) + int(close > bb_upper)

        if long_count >= self._min_conditions:
            self._last_entry_conditions = long_count
            return Direction.LONG, False
        if short_count >= self._min_conditions:
            self._last_entry_conditions = short_count
            return Direction.SHORT, False

        # Exit: no vol_ok requirement — reversals occur on low volume.
        # Direction-aware: a LONG (entered at the lower band) exits when price
        # reverts up toward the opposite band; a SHORT (entered at the upper
        # band) exits when price reverts down toward the lower band. Exiting a
        # short only when price falls BELOW the lower band (the old logic)
        # would require continuation, not mean reversion, and made short exits
        # near-impossible. This signal-series exit is OR-combined across both
        # directions; the per-position exits below refine it on_bar.
        long_exit = (close > bb_upper * 0.98) and (rsi > self._exit_rsi_overbought)
        short_exit = (close < bb_lower * 1.02) and (rsi < self._exit_rsi_oversold)
        exit_ = long_exit or short_exit
        self._last_entry_conditions = 0
        return None, exit_

    def _runtime_values(self) -> tuple[list[float], list[float]]:
        if len(self._close_values) == len(self._bars):
            return self._close_values, self._volume_values
        return closes(self._bars), volumes(self._bars)

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Vectorized signal generation."""
        if len(df) < self._bb_period:
            empty = pd.Series(False, index=df.index)
            return empty, empty

        close = df["close"]
        volume = df.get("volume", pd.Series(1.0, index=df.index))

        rsi = self._compute_rsi(close)

        bb_middle = close.rolling(self._bb_period).mean()
        bb_std = close.rolling(self._bb_period).std()
        bb_upper = bb_middle + self._bb_std * bb_std
        bb_lower = bb_middle - self._bb_std * bb_std

        vol_ma = volume.rolling(self._volume_period).mean()
        vol_ok = volume > vol_ma * self._volume_threshold

        long_count = vol_ok.astype(int) + (rsi < self._rsi_oversold).astype(int) + (close < bb_lower).astype(int)
        short_count = vol_ok.astype(int) + (rsi > self._rsi_overbought).astype(int) + (close > bb_upper).astype(int)
        long_entries = long_count >= self._min_conditions
        short_entries = short_count >= self._min_conditions
        entries = long_entries | short_entries

        # Direction-aware exits: longs (entered at lower band) exit on upward
        # reversion toward the upper band; shorts (entered at upper band) exit
        # on downward reversion toward the lower band. The old logic exited a
        # short only when price fell BELOW the lower band (continuation), which
        # made short exits near-impossible.
        long_exit = (close > bb_upper * 0.98) & (rsi > self._exit_rsi_overbought)
        short_exit = (close < bb_lower * 1.02) & (rsi < self._exit_rsi_oversold)
        exits = long_exit | short_exit

        # Profit target exit — direction-aware
        long_profit_exits = profit_target_exit(close, long_entries, self._profit_take_pct, self._max_holding_bars, direction=1)
        short_profit_exits = profit_target_exit(close, short_entries, self._profit_take_pct, self._max_holding_bars, direction=-1)
        profit_exits = long_profit_exits | short_profit_exits
        exits = exits | profit_exits

        return entries.fillna(False), exits.fillna(False)

    def _compute_rsi(self, close: pd.Series) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(self._rsi_period).mean()
        avg_loss = loss.rolling(self._rsi_period).mean()
        rs = avg_gain / avg_loss.replace(0, 1e-10)
        return 100 - (100 / (1 + rs))

    def _check_position_exits(self, ctx: StrategyContext, bar: Bar) -> None:
        """Check profit target and max holding exits in on_bar path."""
        if not self._in_position:
            return

        self._bars_since_entry += 1

        # Profit target exit — direction-aware
        if self._entry_direction == Direction.LONG:
            target_price = self._entry_price * (1.0 + self._profit_take_pct)
            if bar.close >= target_price:
                ctx.emit_signal(bar.symbol, Direction.FLAT, strength=0.5, price=bar.close, strategy_id=self.name)
                self._in_position = False
                return
        elif self._entry_direction == Direction.SHORT:
            target_price = self._entry_price * (1.0 - self._profit_take_pct)
            if bar.close <= target_price:
                ctx.emit_signal(bar.symbol, Direction.FLAT, strength=0.5, price=bar.close, strategy_id=self.name)
                self._in_position = False
                return

        # Max holding bars exit
        if self._bars_since_entry >= self._max_holding_bars:
            ctx.emit_signal(bar.symbol, Direction.FLAT, strength=0.5, price=bar.close, strategy_id=self.name)
            self._in_position = False

    def _bars_to_df(self) -> pd.DataFrame:
        if not self._bars:
            return pd.DataFrame()
        data = {
            "timestamp": [b.timestamp for b in self._bars],
            "open": [b.open for b in self._bars],
            "high": [b.high for b in self._bars],
            "low": [b.low for b in self._bars],
            "close": [b.close for b in self._bars],
            "volume": [b.volume for b in self._bars],
        }
        df = pd.DataFrame(data)
        df["symbol"] = self._bars[0].symbol
        return df

    def get_required_indicators(self) -> list[dict[str, Any]]:
        return [
            {"name": "rsi", "params": {"period": self._rsi_period}},
            {"name": "bb", "params": {"period": self._bb_period, "std": self._bb_std}},
        ]
