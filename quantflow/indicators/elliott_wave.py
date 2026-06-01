"""Elliott Wave indicators — ZigZag-based wave detection with Fibonacci ratios.

Implements a practical quantitative approach to Elliott Wave Theory:
1. ZigZag pivot detection to identify swing highs/lows
2. Wave classification using Fibonacci retracement ratios
3. Wave count validation against Elliott's rules
4. Momentum divergence confirmation
"""

from __future__ import annotations

from enum import IntEnum
from typing import Optional

import numpy as np
import pandas as pd


class WaveDegree(IntEnum):
    GRAND_SUPERCYCLE = 0
    SUPERCYCLE = 1
    CYCLE = 2
    PRIMARY = 3
    INTERMEDIATE = 4
    MINOR = 5
    MINUTE = 6
    MINUETTE = 7
    SUBMINUETTE = 8


class WaveType(IntEnum):
    IMPULSE = 1
    CORRECTIVE = 2


class WaveLabel(IntEnum):
    W1 = 1
    W2 = 2
    W3 = 3
    W4 = 4
    W5 = 5
    WA = -1  # A wave
    WB = -2  # B wave
    WC = -3  # C wave


# Fibonacci ratios for wave validation
FIB_RATIOS = {
    "w2_retrace": (0.382, 0.618),   # Wave 2 retraces 38.2%–61.8% of Wave 1
    "w3_extend": (1.618, 2.618),     # Wave 3 extends 161.8%–261.8% of Wave 1
    "w4_retrace": (0.236, 0.382),    # Wave 4 retraces 23.6%–38.2% of Wave 3
    "w5_extend": (0.618, 1.0),       # Wave 5 is 61.8%–100% of Wave 1
    "wc_extend": (0.618, 1.618),     # Wave C is 61.8%–161.8% of Wave A
}


def zigzag(
    high: pd.Series,
    low: pd.Series,
    threshold: float = 0.05,
) -> pd.DataFrame:
    """Detect ZigZag pivots from OHLCV data.

    Args:
        high: Series of high prices.
        low: Series of low prices.
        threshold: Minimum price move ratio (e.g. 0.05 = 5%) to qualify as pivot.

    Returns:
        DataFrame with columns [pivot_idx, pivot_price, pivot_type]
        where pivot_type: 1 = swing high, -1 = swing low.
    """
    if threshold <= 0:
        raise ValueError(f"threshold must be positive, got {threshold}")
    n = len(high)
    if n < 3:
        return pd.DataFrame(columns=["pivot_idx", "pivot_price", "pivot_type"])

    pivots: list[dict] = []
    direction = 0  # 0=undecided, 1=up, -1=down
    last_high_idx = 0
    last_low_idx = 0
    last_high = high.iloc[0]
    last_low = low.iloc[0]

    for i in range(1, n):
        if direction == 0:
            if high.iloc[i] > last_high * (1 + threshold):
                direction = 1
                pivots.append({"pivot_idx": last_low_idx, "pivot_price": last_low, "pivot_type": -1})
                last_high = high.iloc[i]
                last_high_idx = i
            elif low.iloc[i] < last_low * (1 - threshold):
                direction = -1
                pivots.append({"pivot_idx": last_high_idx, "pivot_price": last_high, "pivot_type": 1})
                last_low = low.iloc[i]
                last_low_idx = i
            else:
                if high.iloc[i] > last_high:
                    last_high = high.iloc[i]
                    last_high_idx = i
                if low.iloc[i] < last_low:
                    last_low = low.iloc[i]
                    last_low_idx = i
        elif direction == 1:
            if high.iloc[i] > last_high:
                last_high = high.iloc[i]
                last_high_idx = i
            elif low.iloc[i] < last_high * (1 - threshold):
                direction = -1
                pivots.append({"pivot_idx": last_high_idx, "pivot_price": last_high, "pivot_type": 1})
                last_low = low.iloc[i]
                last_low_idx = i
        elif direction == -1:
            if low.iloc[i] < last_low:
                last_low = low.iloc[i]
                last_low_idx = i
            elif high.iloc[i] > last_low * (1 + threshold):
                direction = 1
                pivots.append({"pivot_idx": last_low_idx, "pivot_price": last_low, "pivot_type": -1})
                last_high = high.iloc[i]
                last_high_idx = i

    # Append final pivot
    if direction == 1:
        pivots.append({"pivot_idx": last_high_idx, "pivot_price": last_high, "pivot_type": 1})
    elif direction == -1:
        pivots.append({"pivot_idx": last_low_idx, "pivot_price": last_low, "pivot_type": -1})

    return pd.DataFrame(pivots)


def classify_impulse(
    pivots: pd.DataFrame,
    tolerance: float = 0.15,
) -> Optional[pd.DataFrame]:
    """Try to classify the last 5 pivots as an impulse wave (1-2-3-4-5).

    Args:
        pivots: Output from zigzag() with pivot_idx, pivot_price, pivot_type.
        tolerance: Fibonacci ratio tolerance (e.g. 0.15 = ±15%).

    Returns:
        DataFrame with wave labels if valid impulse, else None.
    """
    if len(pivots) < 5:
        return None

    # Take last 5 pivots for impulse pattern
    pts = pivots.iloc[-5:].reset_index(drop=True)
    prices = pts["pivot_price"].values

    # Must alternate: low-high-low-high-low (bullish) or high-low-high-low-high (bearish)
    types = pts["pivot_type"].values
    if not (types == [-1, 1, -1, 1, -1]).all() and not (types == [1, -1, 1, -1, 1]).all():
        return None

    is_bullish = types[0] == -1  # starts with low

    # Wave amplitudes
    if is_bullish:
        w1 = prices[1] - prices[0]
        w2 = prices[1] - prices[2]
        w3 = prices[3] - prices[2]
        w4 = prices[3] - prices[4]
        w5 = abs(prices[4] - prices[3]) if len(prices) > 4 else 0
    else:
        w1 = prices[0] - prices[1]
        w2 = prices[2] - prices[1]
        w3 = prices[2] - prices[3]
        w4 = prices[4] - prices[3]
        w5 = abs(prices[3] - prices[4]) if len(prices) > 4 else 0

    if w1 <= 0 or w3 <= 0:
        return None

    # Rule 1: Wave 2 retraces 38.2%–61.8% of Wave 1
    r2 = w2 / w1
    lo, hi = FIB_RATIOS["w2_retrace"]
    if not (lo - tolerance <= r2 <= hi + tolerance):
        return None

    # Rule 2: Wave 3 extends beyond 61.8% of Wave 1 (minimum)
    r3 = w3 / w1
    if r3 < 0.618 - tolerance:
        return None

    # Rule 3: Wave 2 ≠ Wave 4 in pattern (alternation rule - relaxed)
    # Rule 4: Wave 4 does not overlap Wave 1 territory
    if is_bullish:
        if prices[4] >= prices[1]:  # W4 low >= W1 high → overlap
            return None
    else:
        if prices[4] <= prices[1]:  # W4 high <= W1 low → overlap
            return None

    # Valid impulse — assign labels
    result = pts.copy()
    labels = [WaveLabel.W1, WaveLabel.W2, WaveLabel.W3, WaveLabel.W4, WaveLabel.W5]
    result["wave_label"] = labels
    result["wave_type"] = WaveType.IMPULSE
    result["is_bullish"] = is_bullish
    return result


def classify_corrective(
    pivots: pd.DataFrame,
    tolerance: float = 0.20,
) -> Optional[pd.DataFrame]:
    """Try to classify the last 3 pivots as an ABC corrective wave.

    Args:
        pivots: Output from zigzag() with columns.
        tolerance: Fibonacci ratio tolerance.

    Returns:
        DataFrame with wave labels if valid correction, else None.
    """
    if len(pivots) < 3:
        return None

    pts = pivots.iloc[-3:].reset_index(drop=True)
    prices = pts["pivot_price"].values
    types = pts["pivot_type"].values

    if not (types[0] != types[1] and types[1] != types[2]):
        return None

    # A and C are impulse legs, B is retracement
    w_a = abs(prices[1] - prices[0])
    w_b = abs(prices[2] - prices[1])
    w_c = abs(prices[2] - prices[0])

    if w_a <= 0:
        return None

    # B retraces 38.2%–78.6% of A
    r_b = w_b / w_a
    if not (0.236 - tolerance <= r_b <= 0.786 + tolerance):
        return None

    # C is typically 61.8%–161.8% of A
    r_c = w_c / w_a
    lo, hi = FIB_RATIOS["wc_extend"]
    if not (lo - tolerance <= r_c <= hi + tolerance):
        return None

    result = pts.copy()
    result["wave_label"] = [WaveLabel.WA, WaveLabel.WB, WaveLabel.WC]
    result["wave_type"] = WaveType.CORRECTIVE
    result["is_bullish"] = types[0] == -1
    return result


def elliott_wave(
    df: pd.DataFrame,
    zigzag_threshold: float = 0.05,
    fib_tolerance: float = 0.15,
) -> pd.DataFrame:
    """Compute Elliott Wave labels for OHLCV data.

    Strategy:
    1. Run ZigZag to find pivots
    2. Try to classify impulse (5-wave) from last pivots
    3. Fall back to corrective (ABC) classification
    4. Map labels back to original DataFrame index

    Args:
        df: OHLCV DataFrame with 'high' and 'low' columns.
        zigzag_threshold: Minimum move ratio for ZigZag pivot detection.
        fib_tolerance: Fibonacci ratio tolerance.

    Returns:
        DataFrame aligned to input with columns:
        - wave_label: WaveLabel enum value (0 if unclassified)
        - wave_type: WaveType enum value (0 if unclassified)
        - is_bullish: True if bullish wave pattern
        - pivot_price: Price at pivot (NaN if not a pivot)
    """
    result = pd.DataFrame(index=df.index)
    result["wave_label"] = 0
    result["wave_type"] = 0
    result["is_bullish"] = False
    result["pivot_price"] = np.nan

    pivots = zigzag(df["high"], df["low"], threshold=zigzag_threshold)
    if pivots.empty:
        return result

    # Try impulse classification first
    wave_df = classify_impulse(pivots, tolerance=fib_tolerance)
    if wave_df is None:
        # Fall back to corrective
        wave_df = classify_corrective(pivots, tolerance=fib_tolerance + 0.05)

    if wave_df is not None:
        for _, row in wave_df.iterrows():
            idx = df.index[row["pivot_idx"]]
            if idx in result.index:
                result.loc[idx, "wave_label"] = int(row["wave_label"])
                result.loc[idx, "wave_type"] = int(row["wave_type"])
                result.loc[idx, "is_bullish"] = row["is_bullish"]
                result.loc[idx, "pivot_price"] = row["pivot_price"]

    return result


def compute_fibonacci_levels(
    wave_start: float,
    wave_end: float,
) -> dict[str, float]:
    """Compute Fibonacci retracement/extension levels for a wave.

    Args:
        wave_start: Start price of the wave.
        wave_end: End price of the wave.

    Returns:
        Dict of level name → price value.
    """
    amplitude = wave_end - wave_start
    is_up = amplitude > 0

    levels = {}
    for ratio in [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618, 2.618]:
        price = wave_end - amplitude * ratio if is_up else wave_end + amplitude * ratio
        label = f"fib_{ratio:.3f}"
        levels[label] = price

    return levels


def wave_momentum_divergence(
    close: pd.Series,
    rsi: pd.Series,
    pivots: pd.DataFrame,
    lookback: int = 5,
) -> pd.Series:
    """Detect momentum divergence at wave endpoints.

    Bullish divergence: price makes lower low but RSI makes higher low → W5 exhaustion.
    Bearish divergence: price makes higher high but RSI makes lower high → W5 exhaustion.

    Returns:
        Series with 1=bullish divergence, -1=bearish divergence, 0=none.
    """
    result = pd.Series(0, index=close.index, dtype=int)

    if len(pivots) < 4:
        return result

    for i in range(2, len(pivots)):
        p = pivots.iloc[i]
        p_prev = pivots.iloc[i - 2]

        if p["pivot_idx"] < lookback or p_prev["pivot_idx"] < lookback:
            continue

        idx = p["pivot_idx"]
        idx_prev = p_prev["pivot_idx"]

        if idx >= len(close) or idx_prev >= len(close):
            continue

        if p["pivot_type"] == -1:  # Swing low
            if close.iloc[idx] < close.iloc[idx_prev] and rsi.iloc[idx] > rsi.iloc[idx_prev]:
                result.iloc[idx] = 1  # Bullish divergence
        elif p["pivot_type"] == 1:  # Swing high
            if close.iloc[idx] > close.iloc[idx_prev] and rsi.iloc[idx] < rsi.iloc[idx_prev]:
                result.iloc[idx] = -1  # Bearish divergence

    return result
