"""Volatility breakout strategy."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from quantflow.common.models import Bar, Direction
from quantflow.indicators.volatility import atr, bollinger_bands, keltner_channel
from quantflow.strategy.base import StrategyBase, StrategyContext
from quantflow.strategy.templates._runtime import (
    closes,
    ewm_next,
    ewm_series,
    highs,
    lows,
    profit_target_exit,
    rolling_average_true_ranges,
    rolling_mean_at,
    rolling_mean_optional_at,
    rolling_std_at,
    true_range_value,
    volumes,
)

logger = logging.getLogger(__name__)


class VolatilityBreakoutStrategy(StrategyBase):
    """Detect low-volatility to high-volatility state transitions."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(name="volatility_breakout", params=params)
        self.required_regime = "trending"
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
        self._min_conditions: int = p.get("min_conditions", 3)
        self._profit_take_pct: float = p.get("take_profit_pct", p.get("profit_take_pct", 0.05))
        self._max_holding_bars: int = p.get("max_holding_bars", 15)
        self._trailing_stop_atr_mult: float = p.get(
            "trailing_stop_atr_multiplier", p.get("trailing_stop_atr_mult", 2.5)
        )
        self._stop_loss_pct: float = p.get("stop_loss_pct", 0.0)

        self._bars: list[Bar] = []
        self._close_values: list[float] = []
        self._high_values: list[float] = []
        self._low_values: list[float] = []
        self._volume_values: list[float] = []
        self._true_range_values: list[float] = []
        self._atr_values: list[float | None] = []
        self._keltner_atr_values: list[float | None] = []
        self._keltner_ema_value: float | None = None
        self._kc_upper_values: list[float | None] = []
        self._kc_lower_values: list[float | None] = []
        self._bb_middle_values: list[float | None] = []
        self._bb_upper_values: list[float | None] = []
        self._bb_lower_values: list[float | None] = []
        self._bb_width_values: list[float | None] = []
        self._bb_width_ma_values: list[float | None] = []
        # Position tracking for on_bar exit mechanisms
        self._in_position: bool = False
        self._entry_direction: Direction | None = None
        self._entry_price: float = 0.0
        self._bars_since_entry: int = 0
        self._highest_since_entry: float = 0.0
        self._lowest_since_entry: float = float("inf")
        self._last_entry_direction: Direction | None = None
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
        """Event-driven bar handler using an incremental latest-row path."""
        self._bars.append(bar)
        self._close_values.append(bar.close)
        self._high_values.append(bar.high)
        self._low_values.append(bar.low)
        self._volume_values.append(bar.volume)
        if len(self._close_values) == len(self._bars):
            self._append_runtime_state(bar)

        if len(self._bars) > self._max_bars:
            self._bars = self._bars[-self._max_bars :]
            self._close_values = self._close_values[-self._max_bars :]
            self._high_values = self._high_values[-self._max_bars :]
            self._low_values = self._low_values[-self._max_bars :]
            self._volume_values = self._volume_values[-self._max_bars :]
            self._true_range_values = self._true_range_values[-self._max_bars :]
            self._atr_values = self._atr_values[-self._max_bars :]
            self._keltner_atr_values = self._keltner_atr_values[-self._max_bars :]
            self._kc_upper_values = self._kc_upper_values[-self._max_bars :]
            self._kc_lower_values = self._kc_lower_values[-self._max_bars :]
            self._bb_middle_values = self._bb_middle_values[-self._max_bars :]
            self._bb_upper_values = self._bb_upper_values[-self._max_bars :]
            self._bb_lower_values = self._bb_lower_values[-self._max_bars :]
            self._bb_width_values = self._bb_width_values[-self._max_bars :]
            self._bb_width_ma_values = self._bb_width_ma_values[-self._max_bars :]

        min_bars = max(self._atr_period * 2, self._bb_period, self._keltner_ema_period)
        if len(self._bars) < min_bars:
            return

        entry, exit_ = self._latest_signal()
        if entry and not self._in_position:
            # Use direction from _latest_signal instead of hardcoded LONG
            direction = self._last_entry_direction or Direction.LONG
            ctx.emit_signal(
                bar.symbol,
                direction,
                strength=0.8,
                price=bar.close,
                strategy_id=self.name,
            )
            self._in_position = True
            self._entry_direction = direction
            self._entry_price = bar.close
            self._bars_since_entry = 0
            self._highest_since_entry = bar.high
            self._lowest_since_entry = bar.low
        elif exit_ and self._in_position:
            ctx.emit_signal(
                bar.symbol,
                Direction.FLAT,
                strength=0.5,
                price=bar.close,
                strategy_id=self.name,
            )
            self._in_position = False

        # on_bar exit mechanisms: profit target + trailing stop + max holding
        self._check_position_exits(ctx, bar)

    def _latest_signal(self) -> tuple[bool, bool]:
        """Compute the latest event-mode signal without rebuilding a DataFrame."""
        close_values, high_values, low_values, volume_values = self._runtime_values()
        last_idx = len(close_values) - 1

        if self._runtime_state_is_current():
            atr_values = self._atr_values
            atr_value = atr_values[-1]
            atr_ma = rolling_mean_optional_at(atr_values, last_idx, self._atr_period * 2)
            bb_middle = self._bb_middle_values[-1]
            bb_upper = self._bb_upper_values[-1]
            bb_lower = self._bb_lower_values[-1]
            bb_width = self._bb_width_values[-1]
            bb_width_ma = self._bb_width_ma_values[-1]
            previous_bb_upper = self._bb_upper_values[last_idx - 1]
            previous_bb_lower = self._bb_lower_values[last_idx - 1]
            previous_kc_upper = self._kc_upper_values[last_idx - 1]
            previous_kc_lower = self._kc_lower_values[last_idx - 1]
        else:
            atr_values = rolling_average_true_ranges(
                high_values,
                low_values,
                close_values,
                self._atr_period,
            )
            atr_value = atr_values[-1]
            atr_ma = rolling_mean_optional_at(atr_values, last_idx, self._atr_period * 2)
            bb_middle = rolling_mean_at(close_values, last_idx, self._bb_period)
            bb_std = rolling_std_at(close_values, last_idx, self._bb_period)
            previous_bb = self._bollinger_at(last_idx - 1, close_values)
            previous_kc = self._keltner_at(
                last_idx - 1,
                high_values,
                low_values,
                close_values,
            )
            if bb_middle is None or bb_std is None or previous_bb is None or previous_kc is None:
                return False, False
            bb_upper = bb_middle + self._bb_std * bb_std
            bb_lower = bb_middle - self._bb_std * bb_std
            if bb_middle == 0:
                return False, False
            bb_width = (bb_upper - bb_lower) / bb_middle
            bb_width_ma = self._bb_width_mean_at(last_idx, close_values)
            previous_bb_upper, previous_bb_lower = previous_bb
            previous_kc_upper, previous_kc_lower = previous_kc

        volume_ma = rolling_mean_at(volume_values, last_idx, self._volume_period)
        if (
            atr_value is None
            or atr_ma is None
            or bb_middle is None
            or bb_upper is None
            or bb_lower is None
            or bb_width is None
            or bb_width_ma is None
            or previous_bb_upper is None
            or previous_bb_lower is None
            or previous_kc_upper is None
            or previous_kc_lower is None
            or volume_ma is None
            or bb_middle == 0
        ):
            return False, False

        previous_squeeze = (
            previous_bb_lower > previous_kc_lower and previous_bb_upper < previous_kc_upper
        )
        atr_spike = atr_value > atr_ma * self._atr_threshold
        bb_expanding = bb_width > bb_width_ma
        vol_surge = volume_values[-1] > volume_ma * self._volume_threshold

        close = close_values[-1]
        long_count = (
            int(atr_spike)
            + int(bb_expanding)
            + int(close > bb_upper)
            + int(vol_surge)
            + int(previous_squeeze)
        )
        short_count = (
            int(atr_spike)
            + int(bb_expanding)
            + int(close < bb_lower)
            + int(vol_surge)
            + int(previous_squeeze)
        )
        entry = long_count >= self._min_conditions or short_count >= self._min_conditions
        if long_count >= self._min_conditions:
            self._last_entry_direction = Direction.LONG
        elif short_count >= self._min_conditions:
            self._last_entry_direction = Direction.SHORT
        else:
            self._last_entry_direction = None

        atr_shrink = atr_value < atr_ma * self._atr_shrink_exit
        middle_return = False
        if self._bb_middle_exit:
            middle_return = abs(close - bb_middle) / bb_middle < 0.005
        return entry, atr_shrink or middle_return

    def _append_runtime_state(self, bar: Bar) -> None:
        previous_close = self._close_values[-2] if len(self._close_values) > 1 else None
        true_range = true_range_value(bar.high, bar.low, bar.close, previous_close)
        self._true_range_values.append(true_range)
        last_idx = len(self._true_range_values) - 1

        self._atr_values.append(
            rolling_mean_at(self._true_range_values, last_idx, self._atr_period)
        )
        keltner_atr = rolling_mean_at(
            self._true_range_values,
            last_idx,
            self._keltner_atr_period,
        )
        self._keltner_atr_values.append(keltner_atr)
        self._keltner_ema_value = ewm_next(
            self._keltner_ema_value,
            bar.close,
            self._keltner_ema_period,
        )
        if keltner_atr is None:
            self._kc_upper_values.append(None)
            self._kc_lower_values.append(None)
        else:
            self._kc_upper_values.append(
                self._keltner_ema_value + self._keltner_multiplier * keltner_atr
            )
            self._kc_lower_values.append(
                self._keltner_ema_value - self._keltner_multiplier * keltner_atr
            )

        bb_middle = rolling_mean_at(self._close_values, last_idx, self._bb_period)
        bb_std = rolling_std_at(self._close_values, last_idx, self._bb_period)
        self._bb_middle_values.append(bb_middle)
        if bb_middle is None or bb_std is None or bb_middle == 0:
            self._bb_upper_values.append(None)
            self._bb_lower_values.append(None)
            self._bb_width_values.append(None)
        else:
            bb_upper = bb_middle + self._bb_std * bb_std
            bb_lower = bb_middle - self._bb_std * bb_std
            self._bb_upper_values.append(bb_upper)
            self._bb_lower_values.append(bb_lower)
            self._bb_width_values.append((bb_upper - bb_lower) / bb_middle)
        self._bb_width_ma_values.append(
            rolling_mean_optional_at(self._bb_width_values, last_idx, self._bb_period)
        )

    def _runtime_state_is_current(self) -> bool:
        return (
            len(self._close_values) == len(self._bars)
            and len(self._atr_values) == len(self._bars)
            and len(self._bb_width_ma_values) == len(self._bars)
            and len(self._kc_upper_values) == len(self._bars)
            and len(self._kc_lower_values) == len(self._bars)
        )

    def _runtime_values(self) -> tuple[list[float], list[float], list[float], list[float]]:
        if len(self._close_values) == len(self._bars):
            return self._close_values, self._high_values, self._low_values, self._volume_values
        return closes(self._bars), highs(self._bars), lows(self._bars), volumes(self._bars)

    def _bollinger_at(
        self,
        index: int,
        close_values: list[float],
    ) -> tuple[float, float] | None:
        middle = rolling_mean_at(close_values, index, self._bb_period)
        std = rolling_std_at(close_values, index, self._bb_period)
        if middle is None or std is None:
            return None
        return middle + self._bb_std * std, middle - self._bb_std * std

    def _bb_width_mean_at(self, index: int, close_values: list[float]) -> float | None:
        if index + 1 < (self._bb_period * 2) - 1:
            return None
        widths: list[float] = []
        for width_idx in range(index + 1 - self._bb_period, index + 1):
            bands = self._bollinger_at(width_idx, close_values)
            middle = rolling_mean_at(close_values, width_idx, self._bb_period)
            if bands is None or middle is None or middle == 0:
                return None
            upper, lower = bands
            widths.append((upper - lower) / middle)
        return sum(widths) / float(self._bb_period)

    def _keltner_at(
        self,
        index: int,
        high_values: list[float],
        low_values: list[float],
        close_values: list[float],
    ) -> tuple[float, float] | None:
        if index < 0:
            return None
        ema_values = ewm_series(close_values[: index + 1], self._keltner_ema_period)
        atr_values = rolling_average_true_ranges(
            high_values[: index + 1],
            low_values[: index + 1],
            close_values[: index + 1],
            self._keltner_atr_period,
        )
        atr_value = atr_values[-1] if atr_values else None
        if not ema_values or atr_value is None:
            return None
        middle = ema_values[-1]
        upper = middle + self._keltner_multiplier * atr_value
        lower = middle - self._keltner_multiplier * atr_value
        return upper, lower

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

        long_count = (
            atr_spike.astype(int)
            + bb_expanding.astype(int)
            + (close > bb_upper).astype(int)
            + vol_surge.astype(int)
            + previous_squeeze.astype(int)
        )
        short_count = (
            atr_spike.astype(int)
            + bb_expanding.astype(int)
            + (close < bb_lower).astype(int)
            + vol_surge.astype(int)
            + previous_squeeze.astype(int)
        )
        long_entries = long_count >= self._min_conditions
        short_entries = short_count >= self._min_conditions
        entries = long_entries | short_entries

        atr_shrink = atr_val < atr_ma * self._atr_shrink_exit
        if self._bb_middle_exit:
            middle_return = (close - bb_middle).abs() / bb_middle < 0.005
        else:
            middle_return = pd.Series(False, index=df.index)
        exits = atr_shrink | middle_return

        # Profit target exit — direction-aware
        long_profit_exits = profit_target_exit(
            close, long_entries, self._profit_take_pct, self._max_holding_bars, direction=1
        )
        short_profit_exits = profit_target_exit(
            close, short_entries, self._profit_take_pct, self._max_holding_bars, direction=-1
        )
        profit_exits = long_profit_exits | short_profit_exits

        # Trailing stop exit — direction-aware, track HIGH for longs, LOW for shorts
        highest = high.copy()
        lowest = low.copy()
        in_long = False
        in_short = False
        for i in range(len(close)):
            if long_entries.iloc[i] and not in_long and not in_short:
                in_long = True
            elif short_entries.iloc[i] and not in_short and not in_long:
                in_short = True
            if in_long:
                highest.iloc[i] = max(
                    float(high.iloc[i]),
                    float(highest.iloc[i - 1]) if i > 0 else float(high.iloc[i]),
                )
                if exits.iloc[i] or profit_exits.iloc[i]:
                    in_long = False
            if in_short:
                lowest.iloc[i] = min(
                    float(low.iloc[i]), float(lowest.iloc[i - 1]) if i > 0 else float(low.iloc[i])
                )
                if exits.iloc[i] or profit_exits.iloc[i]:
                    in_short = False
            if not in_long:
                highest.iloc[i] = float(high.iloc[i])
            if not in_short:
                lowest.iloc[i] = float(low.iloc[i])

        long_trailing_exits = close < highest - atr_val * self._trailing_stop_atr_mult
        short_trailing_exits = close > lowest + atr_val * self._trailing_stop_atr_mult
        trailing_exits = long_trailing_exits | short_trailing_exits

        exits = exits | profit_exits | trailing_exits

        return entries.astype(bool), exits.astype(bool)

    def _check_position_exits(self, ctx: StrategyContext, bar: Bar) -> None:
        """Check profit target, trailing stop, and max holding exits in on_bar path."""
        if not self._in_position:
            return

        self._bars_since_entry += 1
        self._highest_since_entry = max(self._highest_since_entry, bar.high)
        self._lowest_since_entry = min(self._lowest_since_entry, bar.low)

        # Profit target exit — direction-aware
        if self._entry_direction == Direction.LONG:
            target_price = self._entry_price * (1.0 + self._profit_take_pct)
            if bar.close >= target_price:
                ctx.emit_signal(
                    bar.symbol, Direction.FLAT, strength=0.5, price=bar.close, strategy_id=self.name
                )
                self._in_position = False
                return
        elif self._entry_direction == Direction.SHORT:
            target_price = self._entry_price * (1.0 - self._profit_take_pct)
            if bar.close <= target_price:
                ctx.emit_signal(
                    bar.symbol, Direction.FLAT, strength=0.5, price=bar.close, strategy_id=self.name
                )
                self._in_position = False
                return

        # Max holding bars exit
        if self._bars_since_entry >= self._max_holding_bars:
            ctx.emit_signal(
                bar.symbol, Direction.FLAT, strength=0.5, price=bar.close, strategy_id=self.name
            )
            self._in_position = False
            return

        # Trailing stop exit — direction-aware
        if self._atr_values and self._atr_values[-1] is not None:
            atr_val = self._atr_values[-1]
            if self._entry_direction == Direction.LONG:
                trailing_level = self._highest_since_entry - atr_val * self._trailing_stop_atr_mult
                if bar.close < trailing_level:
                    ctx.emit_signal(
                        bar.symbol,
                        Direction.FLAT,
                        strength=0.5,
                        price=bar.close,
                        strategy_id=self.name,
                    )
                    self._in_position = False
            elif self._entry_direction == Direction.SHORT:
                trailing_level = self._lowest_since_entry + atr_val * self._trailing_stop_atr_mult
                if bar.close > trailing_level:
                    ctx.emit_signal(
                        bar.symbol,
                        Direction.FLAT,
                        strength=0.5,
                        price=bar.close,
                        strategy_id=self.name,
                    )
                    self._in_position = False

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
