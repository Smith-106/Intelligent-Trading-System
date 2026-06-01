"""Wave channel calculator for Elliott Wave analysis.

Draws parallel channels connecting W1 and W3 highs with a parallel
through W2 low. Channel upper band often marks W5 termination (S-004).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from quantflow.indicators.base import FactorBase
from quantflow.indicators.wave_models import WaveCount, WavePattern


@dataclass
class ChannelResult:
    """Wave channel calculation result."""
    upper_band: pd.Series | None = None  # Channel upper band
    lower_band: pd.Series | None = None  # Channel lower band
    w5_target: float | None = None  # Projected W5 target at upper band


class WaveChannel(FactorBase):
    """Elliott Wave channel calculator.

    Constructs a parallel channel from wave structure:
    - Upper band: connects W1 and W3 high points
    - Lower band: parallel line through W2 low point
    - W5 target: where price meets the upper band (S-004)

    The upper band frequently marks W5 termination, providing an
    auxiliary validation condition for W5 completion.
    """

    name = "wave_channel"

    def compute(self, df: pd.DataFrame, **params: Any) -> pd.Series:
        """Compute channel and return W5 target price."""
        wave_count = params.get("wave_count")
        if wave_count is None or wave_count.pattern != WavePattern.IMPULSE:
            return pd.Series(float("nan"), index=df.index)

        result = self.calculate(df, wave_count)
        w5_target = result.w5_target if result.w5_target is not None else float("nan")
        return pd.Series(w5_target, index=df.index)

    def calculate(self, df: pd.DataFrame, wave_count: WaveCount) -> ChannelResult:
        """Calculate wave channel from impulse wave count.

        Requires at least W1, W2, W3 to construct the channel.
        """
        waves = wave_count.waves

        if wave_count.pattern != WavePattern.IMPULSE:
            return ChannelResult()

        if not all(k in waves for k in [1, 2, 3]):
            return ChannelResult()

        w1 = waves[1]
        w2 = waves[2]
        w3 = waves[3]

        is_bullish = w1.end.price > w1.start.price

        # Channel reference points
        if is_bullish:
            # Upper band: W1 peak to W3 peak
            p1_idx, p1_price = w1.end.index, w1.end.price
            p2_idx, p2_price = w3.end.index, w3.end.price
            # Lower band: through W2 low
            anchor_idx, anchor_price = w2.end.index, w2.end.price
        else:
            # Lower band: W1 trough to W3 trough
            p1_idx, p1_price = w1.end.index, w1.end.price
            p2_idx, p2_price = w3.end.index, w3.end.price
            anchor_idx, anchor_price = w2.end.index, w2.end.price

        # Calculate slope of the main line
        idx_diff = p2_idx - p1_idx
        if idx_diff == 0:
            return ChannelResult()

        slope = (p2_price - p1_price) / idx_diff
        intercept = p1_price - slope * p1_idx

        # Parallel line offset
        anchor_on_main = slope * anchor_idx + intercept
        offset = anchor_price - anchor_on_main

        # Build band Series
        n = len(df)
        indices = np.arange(n)

        if is_bullish:
            upper_prices = slope * indices + intercept
            lower_prices = slope * indices + intercept + offset
        else:
            lower_prices = slope * indices + intercept
            upper_prices = slope * indices + intercept + offset

        upper_band = pd.Series(upper_prices, index=df.index)
        lower_band = pd.Series(lower_prices, index=df.index)

        # Project W5 target: intersection of upper band with W5
        w5_target = None
        if 4 in waves:
            w4 = waves[4]
            # Estimate W5 arrival time (similar duration to W1)
            w1_duration = w1.end.index - w1.start.index
            projected_w5_idx = w4.end.index + w1_duration
            if projected_w5_idx < n:
                w5_target = float(upper_prices[projected_w5_idx])
            else:
                # Extrapolate
                w5_target = float(slope * projected_w5_idx + intercept) if is_bullish else float(slope * projected_w5_idx + intercept + offset)

        return ChannelResult(
            upper_band=upper_band,
            lower_band=lower_band,
            w5_target=w5_target,
        )
