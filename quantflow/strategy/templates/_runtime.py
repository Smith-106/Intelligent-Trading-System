"""Small numeric helpers for event-driven strategy hot paths."""

from __future__ import annotations

import math
from collections.abc import Sequence

import pandas as pd

from quantflow.common.models import Bar


def closes(bars: Sequence[Bar]) -> list[float]:
    return [bar.close for bar in bars]


def highs(bars: Sequence[Bar]) -> list[float]:
    return [bar.high for bar in bars]


def lows(bars: Sequence[Bar]) -> list[float]:
    return [bar.low for bar in bars]


def volumes(bars: Sequence[Bar]) -> list[float]:
    return [bar.volume for bar in bars]


def rolling_mean_at(values: Sequence[float], index: int, period: int) -> float | None:
    if period <= 0 or index + 1 < period:
        return None
    window = values[index + 1 - period : index + 1]
    return sum(window) / period


def rolling_std_at(values: Sequence[float], index: int, period: int) -> float | None:
    if period <= 0 or index + 1 < period:
        return None
    window = values[index + 1 - period : index + 1]
    if len(window) < 2:
        return None
    mean = sum(window) / period
    variance = sum((value - mean) ** 2 for value in window) / (period - 1)
    return math.sqrt(variance)


def ewm_series(values: Sequence[float], span: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (span + 1.0)
    result = [float(values[0])]
    current = result[0]
    for value in values[1:]:
        current = (float(value) * alpha) + (current * (1.0 - alpha))
        result.append(current)
    return result


def ewm_next(previous: float | None, value: float, span: int) -> float:
    if previous is None:
        return float(value)
    alpha = 2.0 / (span + 1.0)
    return (float(value) * alpha) + (previous * (1.0 - alpha))


def simple_rsi_last(values: Sequence[float], period: int) -> float | None:
    if period <= 0 or len(values) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    start = len(values) - period
    for idx in range(start, len(values)):
        delta = values[idx] - values[idx - 1]
        if delta > 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    rs = avg_gain / (avg_loss if avg_loss != 0 else 1e-10)
    return 100.0 - (100.0 / (1.0 + rs))


def true_range_value(high: float, low: float, close: float, previous_close: float | None) -> float:
    if previous_close is None:
        return high - low
    return max(high - low, abs(high - previous_close), abs(low - previous_close))


def true_ranges(
    high_values: Sequence[float], low_values: Sequence[float], close_values: Sequence[float]
) -> list[float]:
    ranges: list[float] = []
    for idx, high in enumerate(high_values):
        low = low_values[idx]
        if idx == 0:
            ranges.append(high - low)
            continue
        prev_close = close_values[idx - 1]
        ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return ranges


def rolling_average_true_ranges(
    high_values: Sequence[float],
    low_values: Sequence[float],
    close_values: Sequence[float],
    period: int,
) -> list[float | None]:
    ranges = true_ranges(high_values, low_values, close_values)
    values: list[float | None] = []
    for idx in range(len(ranges)):
        values.append(rolling_mean_at(ranges, idx, period))
    return values


def rolling_mean_optional_at(
    values: Sequence[float | None],
    index: int,
    period: int,
) -> float | None:
    if period <= 0 or index + 1 < period:
        return None
    window = values[index + 1 - period : index + 1]
    if any(value is None for value in window):
        return None
    checked = [float(value) for value in window if value is not None]
    return sum(checked) / period


def profit_target_exit(
    close: pd.Series,
    entries: pd.Series,
    profit_take_pct: float,
    max_holding_bars: int,
    direction: int = 1,
) -> pd.Series:
    """Compute boolean exit series for profit target + max holding period.

    Exits when price crosses profit target in the given direction,
    or holding period exceeds max_holding_bars since entry.

    Args:
        close: Close price series.
        entries: Boolean entry signal series.
        profit_take_pct: Profit target as fraction (e.g. 0.10 = 10%).
        max_holding_bars: Maximum bars to hold a position.
        direction: 1 for LONG (default), -1 for SHORT.

    Returns:
        Boolean Series indicating profit target / max-hold exit signals.
    """
    n = len(close)
    exits = pd.Series(False, index=close.index, dtype=bool)

    entry_price = 0.0
    in_position = False
    bars_since_entry = 0

    for i in range(n):
        if entries.iloc[i] and not in_position:
            entry_price = float(close.iloc[i])
            in_position = True
            bars_since_entry = 0
            continue

        if in_position:
            bars_since_entry += 1
            if direction == 1:  # LONG
                target_price = entry_price * (1.0 + profit_take_pct)
                if float(close.iloc[i]) >= target_price or bars_since_entry >= max_holding_bars:
                    exits.iloc[i] = True
                    in_position = False
            else:  # SHORT
                target_price = entry_price * (1.0 - profit_take_pct)
                if float(close.iloc[i]) <= target_price or bars_since_entry >= max_holding_bars:
                    exits.iloc[i] = True
                    in_position = False

    return exits
