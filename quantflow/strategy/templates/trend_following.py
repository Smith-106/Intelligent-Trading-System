"""Trend following strategy: MA crossover + MACD + RSI + ATR + volume filters."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyBase, StrategyContext
from quantflow.strategy.templates._runtime import (
    closes,
    ewm_next,
    ewm_series,
    highs,
    lows,
    rolling_average_true_ranges,
    rolling_mean_at,
    rolling_mean_optional_at,
    simple_rsi_last,
    true_range_value,
    volumes,
)

logger = logging.getLogger(__name__)


class TrendFollowingStrategy(StrategyBase):
    """Multi-filter trend following strategy.

    Entry long: fast MA > slow MA, MACD histogram > 0, RSI below overbought,
    ATR below cap, and volume above threshold.
    Entry short: symmetric trend-down conditions.
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(name="trend_following", params=params)
        p = self._params
        self._fast_period = p.get("fast_ma_period", 10)
        self._slow_period = p.get("slow_ma_period", 30)
        self._macd_fast = p.get("macd_fast", 12)
        self._macd_slow = p.get("macd_slow", 26)
        self._macd_signal = p.get("macd_signal", 9)
        self._rsi_period = p.get("rsi_period", 14)
        self._rsi_overbought = p.get("rsi_overbought", 70)
        self._rsi_oversold = p.get("rsi_oversold", 30)
        self._atr_period = p.get("atr_period", 14)
        self._atr_multiplier = p.get("atr_multiplier", 2.0)
        self._volume_period = p.get("volume_period", 20)
        self._volume_threshold = p.get("volume_threshold", 1.0)

        self._bars: list[Bar] = []
        self._close_values: list[float] = []
        self._high_values: list[float] = []
        self._low_values: list[float] = []
        self._volume_values: list[float] = []
        self._ema_fast_value: float | None = None
        self._ema_slow_value: float | None = None
        self._macd_signal_value: float | None = None
        self._macd_hist_value: float | None = None
        self._true_range_values: list[float] = []
        self._atr_values: list[float | None] = []
        self._max_bars = (
            max(
                self._slow_period,
                self._macd_slow,
                self._rsi_period,
                self._atr_period,
                self._volume_period,
            )
            + 50
        )

    def on_init(self, ctx: StrategyContext) -> None:
        ctx.params = self._params

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        """Event-driven bar handler using an incremental latest-row path."""
        self._bars.append(bar)
        self._close_values.append(bar.close)
        self._high_values.append(bar.high)
        self._low_values.append(bar.low)
        self._volume_values.append(bar.volume)
        if len(self._close_values) == len(self._bars):
            self._append_runtime_state(bar)

        if len(self._bars) > self._max_bars:
            self._bars = self._bars[-self._max_bars :]
            self._close_values = self._close_values[-self._max_bars :]
            self._high_values = self._high_values[-self._max_bars :]
            self._low_values = self._low_values[-self._max_bars :]
            self._volume_values = self._volume_values[-self._max_bars :]
            self._true_range_values = self._true_range_values[-self._max_bars :]
            self._atr_values = self._atr_values[-self._max_bars :]

        if len(self._bars) < self._slow_period + self._macd_signal:
            return

        entry, exit_ = self._latest_signal()
        if entry:
            ctx.emit_signal(
                bar.symbol,
                Direction.LONG,
                strength=0.8,
                price=bar.close,
                strategy_id=self.name,
            )
        elif exit_:
            ctx.emit_signal(
                bar.symbol,
                Direction.SHORT,
                strength=0.5,
                price=bar.close,
                strategy_id=self.name,
            )

    def _latest_signal(self) -> tuple[bool, bool]:
        """Compute the last signal without rebuilding a DataFrame."""
        close_values, high_values, low_values, volume_values = self._runtime_values()
        last_idx = len(close_values) - 1

        fast_ma = rolling_mean_at(close_values, last_idx, self._fast_period)
        slow_ma = rolling_mean_at(close_values, last_idx, self._slow_period)
        volume_ma = rolling_mean_at(volume_values, last_idx, self._volume_period)
        rsi = simple_rsi_last(close_values, self._rsi_period)
        if fast_ma is None or slow_ma is None or volume_ma is None or rsi is None:
            return False, False

        if self._runtime_state_is_current() and self._macd_hist_value is not None:
            macd_hist = self._macd_hist_value
            atr_values = self._atr_values
        else:
            ema_fast = ewm_series(close_values, self._macd_fast)
            ema_slow = ewm_series(close_values, self._macd_slow)
            macd_line = [fast - slow for fast, slow in zip(ema_fast, ema_slow, strict=False)]
            macd_signal = ewm_series(macd_line, self._macd_signal)
            if not macd_signal:
                return False, False
            macd_hist = macd_line[-1] - macd_signal[-1]
            atr_values = rolling_average_true_ranges(
                high_values,
                low_values,
                close_values,
                self._atr_period,
            )

        atr = atr_values[-1]
        atr_cap_mean = rolling_mean_optional_at(atr_values, last_idx, self._slow_period)
        if atr is None or atr_cap_mean is None:
            return False, False
        atr_cap = atr_cap_mean * self._atr_multiplier

        vol_ok = volume_values[-1] > volume_ma * self._volume_threshold
        atr_ok = atr < atr_cap
        trend_up = fast_ma > slow_ma and macd_hist > 0
        trend_down = fast_ma < slow_ma and macd_hist < 0
        entry = trend_up and rsi < self._rsi_overbought and vol_ok and atr_ok
        exit_ = trend_down and rsi > self._rsi_oversold and vol_ok and atr_ok
        return entry, exit_

    def _append_runtime_state(self, bar: Bar) -> None:
        previous_close = self._close_values[-2] if len(self._close_values) > 1 else None
        true_range = true_range_value(bar.high, bar.low, bar.close, previous_close)
        self._true_range_values.append(true_range)
        last_idx = len(self._true_range_values) - 1
        self._atr_values.append(
            rolling_mean_at(self._true_range_values, last_idx, self._atr_period)
        )

        self._ema_fast_value = ewm_next(self._ema_fast_value, bar.close, self._macd_fast)
        self._ema_slow_value = ewm_next(self._ema_slow_value, bar.close, self._macd_slow)
        macd_line = self._ema_fast_value - self._ema_slow_value
        self._macd_signal_value = ewm_next(
            self._macd_signal_value,
            macd_line,
            self._macd_signal,
        )
        self._macd_hist_value = macd_line - self._macd_signal_value

    def _runtime_state_is_current(self) -> bool:
        return len(self._close_values) == len(self._bars) and len(self._atr_values) == len(
            self._bars
        )

    def _runtime_values(self) -> tuple[list[float], list[float], list[float], list[float]]:
        if len(self._close_values) == len(self._bars):
            return self._close_values, self._high_values, self._low_values, self._volume_values
        return closes(self._bars), highs(self._bars), lows(self._bars), volumes(self._bars)

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Vectorized signal generation."""
        if len(df) < self._slow_period + self._macd_signal:
            empty = pd.Series(False, index=df.index)
            return empty, empty

        close = df["close"]
        high = df.get("high", close)
        low = df.get("low", close)
        volume = df.get("volume", pd.Series(1.0, index=df.index))

        fast_ma = close.rolling(self._fast_period).mean()
        slow_ma = close.rolling(self._slow_period).mean()

        ema_fast = close.ewm(span=self._macd_fast, adjust=False).mean()
        ema_slow = close.ewm(span=self._macd_slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        macd_signal = macd_line.ewm(span=self._macd_signal, adjust=False).mean()
        macd_hist = macd_line - macd_signal

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(self._rsi_period).mean()
        avg_loss = loss.rolling(self._rsi_period).mean()
        rs = avg_gain / avg_loss.replace(0, 1e-10)
        rsi = 100 - (100 / (1 + rs))

        tr = pd.concat(
            [
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(self._atr_period).mean()
        atr_cap = atr.rolling(self._slow_period).mean() * self._atr_multiplier

        vol_ma = volume.rolling(self._volume_period).mean()
        vol_ok = volume > vol_ma * self._volume_threshold

        trend_up = (fast_ma > slow_ma) & (macd_hist > 0)
        trend_down = (fast_ma < slow_ma) & (macd_hist < 0)
        rsi_ok_long = rsi < self._rsi_overbought
        rsi_ok_short = rsi > self._rsi_oversold
        atr_ok = atr < atr_cap

        entries = trend_up & rsi_ok_long & vol_ok & atr_ok
        exits = trend_down & rsi_ok_short & vol_ok & atr_ok

        return entries.fillna(False), exits.fillna(False)

    def _bars_to_df(self) -> pd.DataFrame:
        """Convert accumulated bars to a DataFrame."""
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
            {"name": "sma", "params": {"period": self._fast_period}},
            {"name": "sma", "params": {"period": self._slow_period}},
            {
                "name": "macd",
                "params": {
                    "fast": self._macd_fast,
                    "slow": self._macd_slow,
                    "signal": self._macd_signal,
                },
            },
            {"name": "rsi", "params": {"period": self._rsi_period}},
            {"name": "atr", "params": {"period": self._atr_period}},
        ]
