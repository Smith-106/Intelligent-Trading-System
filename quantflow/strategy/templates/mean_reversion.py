"""Mean reversion strategy: RSI + Bollinger Band + volume confirmation."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyBase, StrategyContext
from quantflow.strategy.templates._runtime import (
    closes,
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
        p = self._params
        self._rsi_period = p.get("rsi_period", 14)
        self._rsi_oversold = p.get("rsi_oversold", 30)
        self._rsi_overbought = p.get("rsi_overbought", 70)
        self._bb_period = p.get("bb_period", 20)
        self._bb_std = p.get("bb_std", 2.0)
        self._volume_period = p.get("volume_period", 20)
        self._volume_threshold = p.get("volume_threshold", 0.8)
        self._exit_rsi_overbought = p.get("exit_rsi_overbought", 60)
        self._exit_rsi_oversold = p.get("exit_rsi_oversold", 40)

        self._bars: list[Bar] = []
        self._close_values: list[float] = []
        self._volume_values: list[float] = []
        self._max_bars = max(self._rsi_period, self._bb_period, self._volume_period) + 50

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
        if entry_direction is not None:
            ctx.emit_signal(
                bar.symbol,
                entry_direction,
                strength=0.7,
                price=bar.close,
                strategy_id=self.name,
            )
        elif exit_:
            ctx.emit_signal(
                bar.symbol,
                Direction.FLAT,
                strength=0.3,
                price=bar.close,
                strategy_id=self.name,
            )

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

        if vol_ok and rsi < self._rsi_oversold and close < bb_lower:
            return Direction.LONG, False
        if vol_ok and rsi > self._rsi_overbought and close > bb_upper:
            return Direction.SHORT, False

        exit_ = (close > bb_middle and rsi > self._exit_rsi_overbought) or (
            close < bb_middle and rsi < self._exit_rsi_oversold
        )
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

        entries = vol_ok & (
            ((rsi < self._rsi_oversold) & (close < bb_lower))
            | ((rsi > self._rsi_overbought) & (close > bb_upper))
        )

        exits = ((close > bb_middle) & (rsi > self._exit_rsi_overbought)) | (
            (close < bb_middle) & (rsi < self._exit_rsi_oversold)
        )

        return entries.fillna(False), exits.fillna(False)

    def _compute_rsi(self, close: pd.Series) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(self._rsi_period).mean()
        avg_loss = loss.rolling(self._rsi_period).mean()
        rs = avg_gain / avg_loss.replace(0, 1e-10)
        return 100 - (100 / (1 + rs))

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
