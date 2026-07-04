"""Elliott Wave trend strategy."""

from __future__ import annotations

from typing import Any

import pandas as pd

from quantflow.common.models import Bar, Direction
from quantflow.indicators.elliott_wave import (
    WaveLabel,
    elliott_wave,
    wave_momentum_divergence,
)
from quantflow.strategy.base import StrategyBase, StrategyContext
from quantflow.strategy.templates._runtime import profit_target_exit


class ElliottWaveStrategy(StrategyBase):
    """Trade impulse and correction structures using Elliott Wave labels."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(name="elliott_wave", params=params)
        self.zigzag_threshold = self.params.get("zigzag_threshold", 0.03)
        self.fib_tolerance = self.params.get("fib_tolerance", 0.15)
        self.use_divergence = self.params.get("use_divergence", True)
        self.atr_stop_mult = self.params.get("atr_stop_mult", 1.5)
        self._profit_take_pct: float = self.params.get("take_profit_pct", self.params.get("profit_take_pct", 0.08))
        self._max_holding_bars: int = self.params.get("max_holding_bars", 25)
        self._stop_loss_pct: float = self.params.get("stop_loss_pct", 0.0)
        self._bars: list[Bar] = []
        self._in_position: bool = False
        self._entry_price: float = 0.0
        self._bars_since_entry: int = 0

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        if len(df) < 20:
            empty = pd.Series(False, index=df.index)
            return empty, empty

        wave = elliott_wave(
            df,
            zigzag_threshold=self.zigzag_threshold,
            fib_tolerance=self.fib_tolerance,
        )

        entries = pd.Series(False, index=df.index)
        exits = pd.Series(False, index=df.index)
        labels = wave["wave_label"]

        for i in range(1, len(df)):
            lbl = labels.iloc[i]
            if lbl in (int(WaveLabel.W2), int(WaveLabel.W4), int(WaveLabel.WC)):
                entries.iloc[i] = True
            elif lbl == int(WaveLabel.W5):
                exits.iloc[i] = True

        if self.use_divergence and "rsi_14" in df.columns:
            from quantflow.indicators.elliott_wave import zigzag as zz

            pivots = zz(df["high"], df["low"], threshold=self.zigzag_threshold)
            div = wave_momentum_divergence(df["close"], df["rsi_14"], pivots)
            exits = exits | (div == -1)

        # Profit target exit
        close = df["close"]
        profit_exits = profit_target_exit(close, entries, self._profit_take_pct, self._max_holding_bars)
        exits = exits | profit_exits

        return entries.astype(bool), exits.astype(bool)

    def on_init(self, ctx: StrategyContext) -> None:
        pass

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        """Event-driven bar handler — delegates to generate_signals with accumulated bars."""
        self._bars.append(bar)
        if len(self._bars) > 300:
            self._bars = self._bars[-300:]

        if len(self._bars) < 20:
            return

        df = self._bars_to_df()
        if df.empty:
            return

        entries, exits = self.generate_signals(df)
        if entries.empty:
            return

        last_idx = len(entries) - 1
        if entries.iloc[last_idx] and not self._in_position:
            ctx.emit_signal(bar.symbol, Direction.LONG, strength=0.7, price=bar.close, strategy_id=self.name)
            self._in_position = True
            self._entry_price = bar.close
            self._bars_since_entry = 0
        elif exits.iloc[last_idx] and self._in_position:
            ctx.emit_signal(bar.symbol, Direction.FLAT, strength=0.5, price=bar.close, strategy_id=self.name)
            self._in_position = False

        # on_bar exit mechanisms
        self._check_position_exits(ctx, bar)

    def on_tick(self, ctx: StrategyContext, tick: Any) -> None:
        pass

    def _check_position_exits(self, ctx: StrategyContext, bar: Bar) -> None:
        """Check profit target and max holding exits in on_bar path."""
        if not self._in_position:
            return

        self._bars_since_entry += 1

        # Profit target exit (LONG only — elliott_wave entries are LONG)
        target_price = self._entry_price * (1.0 + self._profit_take_pct)
        if bar.close >= target_price:
            ctx.emit_signal(bar.symbol, Direction.FLAT, strength=0.5, price=bar.close, strategy_id=self.name)
            self._in_position = False
            return

        # Max holding bars exit
        if self._bars_since_entry >= self._max_holding_bars:
            ctx.emit_signal(bar.symbol, Direction.FLAT, strength=0.5, price=bar.close, strategy_id=self.name)
            self._in_position = False

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
