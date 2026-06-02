"""Mean reversion strategy — RSI + Bollinger Band + Volume confirmation."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyBase, StrategyContext

logger = logging.getLogger(__name__)


class MeanReversionStrategy(StrategyBase):
    """Mean reversion strategy using RSI + Bollinger Bands.

    Entry long:  RSI < oversold AND close < BB_lower AND volume > vol_ma
    Entry short: RSI > overbought AND close > BB_upper AND volume > vol_ma
    Exit long:   close > BB_middle OR RSI > exit_overbought
    Exit short:  close < BB_middle OR RSI < exit_oversold
    """

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
        self._max_bars = max(self._rsi_period, self._bb_period, self._volume_period) + 50

    def on_init(self, ctx: StrategyContext) -> None:
        ctx.params = self._params

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        """Event-driven bar handler."""
        self._bars.append(bar)
        if len(self._bars) > self._max_bars:
            self._bars = self._bars[-self._max_bars :]

        if len(self._bars) < self._bb_period:
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
            # Determine direction from RSI
            rsi_val = self._compute_rsi(df["close"]).iloc[last_idx]
            if rsi_val < self._rsi_oversold:
                ctx.emit_signal(
                    symbol, Direction.LONG, strength=0.7, price=bar.close, strategy_id=self.name
                )
            elif rsi_val > self._rsi_overbought:
                ctx.emit_signal(
                    symbol, Direction.SHORT, strength=0.7, price=bar.close, strategy_id=self.name
                )
        elif exits.iloc[last_idx]:
            ctx.emit_signal(
                symbol, Direction.FLAT, strength=0.3, price=bar.close, strategy_id=self.name
            )

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Vectorized signal generation."""
        if len(df) < self._bb_period:
            empty = pd.Series(False, index=df.index)
            return empty, empty

        close = df["close"]
        volume = df.get("volume", pd.Series(1.0, index=df.index))

        # RSI
        rsi = self._compute_rsi(close)

        # Bollinger Bands
        bb_middle = close.rolling(self._bb_period).mean()
        bb_std = close.rolling(self._bb_period).std()
        bb_upper = bb_middle + self._bb_std * bb_std
        bb_lower = bb_middle - self._bb_std * bb_std

        # Volume filter
        vol_ma = volume.rolling(self._volume_period).mean()
        vol_ok = volume > vol_ma * self._volume_threshold

        # Entry: oversold + below BB lower (long) or overbought + above BB upper (short)
        entries = vol_ok & (
            ((rsi < self._rsi_oversold) & (close < bb_lower))
            | ((rsi > self._rsi_overbought) & (close > bb_upper))
        )

        # Exit: price returns to middle band or RSI normalizes
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
