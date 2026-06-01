"""Trend following strategy — MA crossover + MACD + RSI + ATR + Volume filters."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyBase, StrategyContext

logger = logging.getLogger(__name__)


class TrendFollowingStrategy(StrategyBase):
    """Multi-filter trend following strategy.

    Entry long:  fast MA > slow MA AND MACD histogram > 0 AND RSI < overbought
                 AND ATR < volatility cap AND volume > volume threshold
    Entry short: fast MA < slow MA AND MACD histogram < 0 AND RSI > oversold
                 AND ATR < volatility cap AND volume > volume threshold
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

        # State for event-driven mode
        self._bars: list[Bar] = []
        self._max_bars = max(self._slow_period, self._macd_slow, self._rsi_period,
                             self._atr_period, self._volume_period) + 50

    def on_init(self, ctx: StrategyContext) -> None:
        ctx.params = self._params

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        """Event-driven bar handler — accumulate bars and emit signals."""
        self._bars.append(bar)
        if len(self._bars) > self._max_bars:
            self._bars = self._bars[-self._max_bars:]

        # Need enough bars for indicators
        if len(self._bars) < self._slow_period + self._macd_signal:
            return

        df = self._bars_to_df()
        if df.empty:
            return

        entries, exits = self.generate_signals(df)
        if entries.empty:
            return

        last_idx = len(entries) - 1
        symbol = bar.symbol

        if entries.iloc[last_idx]:
            ctx.emit_signal(symbol, Direction.LONG, strength=0.8, price=bar.close,
                            strategy_id=self.name)
        elif exits.iloc[last_idx]:
            # For exits, emit opposite direction to close
            # Check if we have a position — simplified: always signal to exit
            ctx.emit_signal(symbol, Direction.SHORT, strength=0.5, price=bar.close,
                            strategy_id=self.name)

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Vectorized signal generation."""
        if len(df) < self._slow_period + self._macd_signal:
            empty = pd.Series(False, index=df.index)
            return empty, empty

        close = df["close"]
        high = df.get("high", close)
        low = df.get("low", close)
        volume = df.get("volume", pd.Series(1.0, index=df.index))

        # Indicator calculations
        fast_ma = close.rolling(self._fast_period).mean()
        slow_ma = close.rolling(self._slow_period).mean()

        # MACD
        ema_fast = close.ewm(span=self._macd_fast, adjust=False).mean()
        ema_slow = close.ewm(span=self._macd_slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        macd_signal = macd_line.ewm(span=self._macd_signal, adjust=False).mean()
        macd_hist = macd_line - macd_signal

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(self._rsi_period).mean()
        avg_loss = loss.rolling(self._rsi_period).mean()
        rs = avg_gain / avg_loss.replace(0, 1e-10)
        rsi = 100 - (100 / (1 + rs))

        # ATR
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(self._atr_period).mean()
        atr_cap = atr.rolling(self._slow_period).mean() * self._atr_multiplier

        # Volume filter
        vol_ma = volume.rolling(self._volume_period).mean()
        vol_ok = volume > vol_ma * self._volume_threshold

        # Entry conditions
        trend_up = (fast_ma > slow_ma) & (macd_hist > 0)
        trend_down = (fast_ma < slow_ma) & (macd_hist < 0)
        rsi_ok_long = rsi < self._rsi_overbought
        rsi_ok_short = rsi > self._rsi_oversold
        vol_ok_signal = vol_ok
        atr_ok = atr < atr_cap

        entries = trend_up & rsi_ok_long & vol_ok_signal & atr_ok
        exits = trend_down & rsi_ok_short & vol_ok_signal & atr_ok

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
            {"name": "macd", "params": {"fast": self._macd_fast, "slow": self._macd_slow,
                                          "signal": self._macd_signal}},
            {"name": "rsi", "params": {"period": self._rsi_period}},
            {"name": "atr", "params": {"period": self._atr_period}},
        ]
