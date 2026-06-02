"""Elliott Wave trend strategy."""

from __future__ import annotations

from typing import Any

import pandas as pd

from quantflow.common.models import Bar
from quantflow.indicators.elliott_wave import (
    WaveLabel,
    elliott_wave,
    wave_momentum_divergence,
)
from quantflow.strategy.base import StrategyBase, StrategyContext


class ElliottWaveStrategy(StrategyBase):
    """Trade impulse and correction structures using Elliott Wave labels."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(name="elliott_wave", params=params)
        self.zigzag_threshold = self.params.get("zigzag_threshold", 0.03)
        self.fib_tolerance = self.params.get("fib_tolerance", 0.15)
        self.use_divergence = self.params.get("use_divergence", True)
        self.atr_stop_mult = self.params.get("atr_stop_mult", 1.5)

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

        return entries.astype(bool), exits.astype(bool)

    def on_init(self, ctx: StrategyContext) -> None:
        pass

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        pass

    def on_tick(self, ctx: StrategyContext, tick: Any) -> None:
        pass
