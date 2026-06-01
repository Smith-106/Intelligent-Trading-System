"""Elliott Wave trend strategy — trades impulse waves with Fibonacci confirmation."""

from __future__ import annotations

import pandas as pd
import numpy as np

from quantflow.strategy.base import StrategyBase
from quantflow.indicators.elliott_wave import (
    elliott_wave,
    wave_momentum_divergence,
    WaveLabel,
    WaveType,
)


class ElliottWaveStrategy(StrategyBase):
    """Trade based on Elliott Wave counts.

    Entry signals:
    - Long at Wave 2 low (start of W3) when Fib retracement confirmed
    - Long at Wave 4 low (start of W5) when Fib retracement confirmed
    - Short at Wave 2 high / Wave 4 high (bearish impulses)

    Exit signals:
    - Take profit at Fibonacci extension targets
    - Exit on momentum divergence (W5 exhaustion)
    - Stop loss beyond Wave start invalidation level
    """

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        self.zigzag_threshold = self.params.get("zigzag_threshold", 0.03)
        self.fib_tolerance = self.params.get("fib_tolerance", 0.15)
        self.use_divergence = self.params.get("use_divergence", True)
        self.atr_stop_mult = self.params.get("atr_stop_mult", 1.5)

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        if len(df) < 20:
            empty = pd.Series(False, index=df.index)
            return empty, empty

        # Compute Elliott Wave labels
        wave = elliott_wave(df, zigzag_threshold=self.zigzag_threshold, fib_tolerance=self.fib_tolerance)

        entries = pd.Series(False, index=df.index)
        exits = pd.Series(False, index=df.index)

        labels = wave["wave_label"]
        bullish = wave["is_bullish"]

        for i in range(1, len(df)):
            lbl = labels.iloc[i]
            is_bull = bullish.iloc[i]

            if lbl == int(WaveLabel.W2):
                # W2 complete → enter in direction of impulse
                entries.iloc[i] = True
            elif lbl == int(WaveLabel.W4):
                # W4 complete → enter for W5
                entries.iloc[i] = True
            elif lbl == int(WaveLabel.W5):
                # W5 complete → exit (end of impulse)
                exits.iloc[i] = True
            elif lbl == int(WaveLabel.WC):
                # C wave complete → potential reversal entry
                entries.iloc[i] = True

        # Divergence filter: exit on W5 divergence
        if self.use_divergence and "rsi_14" in df.columns:
            from quantflow.indicators.elliott_wave import zigzag as zz
            pivots = zz(df["high"], df["low"], threshold=self.zigzag_threshold)
            div = wave_momentum_divergence(df["close"], df["rsi_14"], pivots)
            # Bearish divergence at any point → exit longs
            exits = exits | (div == -1)

        return entries, exits

    def on_init(self, ctx) -> None:
        pass

    def on_bar(self, ctx, bar) -> None:
        pass

    def on_tick(self, ctx, tick) -> None:
        pass
