"""Volatility breakout strategy."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from quantflow.common.models import Bar, Direction
from quantflow.indicators.volatility import atr, bollinger_bands, keltner_channel
from quantflow.strategy.base import StrategyBase, StrategyContext

logger = logging.getLogger(__name__)


class VolatilityBreakoutStrategy(StrategyBase):
    """Detect low-volatility to high-volatility state transitions."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(name="volatility_breakout", params=params)
        p = self._params
        self._atr_period = p.get("atr_period", 14)
        self._atr_threshold = p.get("atr_threshold", 1.5)
        self._bb_period = p.get("bb_period", 20)
        self._bb_std = p.get("bb_std", 2.0)
        self._keltner_ema_period = p.get("keltner_ema_period", 20)
        self._keltner_atr_period = p.get("keltner_atr_period", 10)
        self._keltner_multiplier = p.get("keltner_multiplier", 2.0)
        self._volume_period = p.get("volume_period", 20)
        self._volume_threshold = p.get("volume_threshold", 1.5)
        self._atr_shrink_exit = p.get("atr_shrink_exit", 0.7)
        self._bb_middle_exit = p.get("bb_middle_exit", True)

        self._bars: list[Bar] = []
        self._max_bars = (
            max(
                self._atr_period,
                self._bb_period,
                self._keltner_ema_period,
                self._keltner_atr_period,
                self._volume_period,
            )
            + 50
        )

    def on_init(self, ctx: StrategyContext) -> None:
        ctx.params = self._params

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        self._bars.append(bar)
        if len(self._bars) > self._max_bars:
            self._bars = self._bars[-self._max_bars :]

        min_bars = max(self._atr_period * 2, self._bb_period, self._keltner_ema_period)
        if len(self._bars) < min_bars:
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
            ctx.emit_signal(
                symbol,
                Direction.LONG,
                strength=0.8,
                price=bar.close,
                strategy_id=self.name,
            )
        elif exits.iloc[last_idx]:
            ctx.emit_signal(
                symbol,
                Direction.FLAT,
                strength=0.5,
                price=bar.close,
                strategy_id=self.name,
            )

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        min_bars = max(self._atr_period * 2, self._bb_period, self._keltner_ema_period)
        if len(df) < min_bars:
            empty = pd.Series(False, index=df.index)
            return empty, empty

        close = df["close"]
        high = df.get("high", close)
        low = df.get("low", close)
        volume = df.get("volume", pd.Series(1.0, index=df.index))

        atr_val = atr(high, low, close, self._atr_period)
        atr_ma = atr_val.rolling(self._atr_period * 2).mean()
        atr_spike = atr_val > atr_ma * self._atr_threshold

        bb = bollinger_bands(close, self._bb_period, self._bb_std)
        bb_upper = bb["bb_upper"]
        bb_middle = bb["bb_middle"]
        bb_lower = bb["bb_lower"]
        bb_width = (bb_upper - bb_lower) / bb_middle
        bb_width_ma = bb_width.rolling(self._bb_period).mean()
        bb_expanding = bb_width > bb_width_ma

        kc = keltner_channel(
            high,
            low,
            close,
            self._keltner_ema_period,
            self._keltner_atr_period,
            self._keltner_multiplier,
        )
        kc_upper = kc["kc_upper"]
        kc_lower = kc["kc_lower"]
        squeeze = (bb_lower > kc_lower) & (bb_upper < kc_upper)
        previous_squeeze = squeeze.shift(1, fill_value=False).astype(bool)

        vol_ma = volume.rolling(self._volume_period).mean()
        vol_surge = volume > vol_ma * self._volume_threshold

        entries_long = atr_spike & bb_expanding & (close > bb_upper) & vol_surge & previous_squeeze
        entries_short = atr_spike & bb_expanding & (close < bb_lower) & vol_surge & previous_squeeze
        entries = entries_long | entries_short

        atr_shrink = atr_val < atr_ma * self._atr_shrink_exit
        if self._bb_middle_exit:
            middle_return = (close - bb_middle).abs() / bb_middle < 0.005
        else:
            middle_return = pd.Series(False, index=df.index)
        exits = atr_shrink | middle_return

        return entries.astype(bool), exits.astype(bool)

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
            {"name": "atr", "params": {"period": self._atr_period}},
            {"name": "bb", "params": {"period": self._bb_period, "std": self._bb_std}},
            {
                "name": "keltner",
                "params": {
                    "ema_period": self._keltner_ema_period,
                    "atr_period": self._keltner_atr_period,
                    "multiplier": self._keltner_multiplier,
                },
            },
        ]
