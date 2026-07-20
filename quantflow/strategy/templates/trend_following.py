"""Trend following strategy: MA crossover + MACD + RSI + ATR + volume filters."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyBase, StrategyContext
from quantflow.strategy.templates._runtime import (
    closes,
    ewm_next,
    ewm_series,
    highs,
    lows,
    profit_target_exit,
    profit_target_exit_series,
    rolling_average_true_ranges,
    rolling_mean_at,
    rolling_mean_optional_at,
    simple_rsi_last,
    true_range_value,
    volumes,
)

logger = logging.getLogger(__name__)


class TrendFollowingStrategy(StrategyBase):
    """Multi-filter trend following strategy.

    Entry long: fast MA > slow MA, MACD histogram > 0, RSI below overbought,
    ATR below cap, and volume above threshold.
    Entry short: symmetric trend-down conditions.
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(name="trend_following", params=params)
        self.required_regime = "trending"
        p = self._params
        self._fast_period = p.get("fast_ma_period", 10)
        self._slow_period = p.get("slow_ma_period", 30)
        self._macd_fast = p.get("macd_fast", 12)
        self._macd_slow = p.get("macd_slow", 26)
        self._macd_signal = p.get("macd_signal", 9)
        self._rsi_period = p.get("rsi_period", 14)
        self._rsi_overbought = p.get("rsi_overbought", 70)
        self._rsi_oversold = p.get("rsi_oversold", 30)
        self._atr_period = p.get("atr_period", 14)
        self._atr_multiplier = p.get("atr_multiplier", 2.0)
        self._volume_period = p.get("volume_period", 20)
        self._volume_threshold = p.get("volume_threshold", 1.0)
        self._min_conditions: int = p.get("min_conditions", 4)
        self._profit_take_pct: float = p.get("take_profit_pct", p.get("profit_take_pct", 0.10))
        self._max_holding_bars: int = p.get("max_holding_bars", 20)
        self._trailing_stop_atr_mult: float = p.get(
            "trailing_stop_atr_multiplier", p.get("trailing_stop_atr_mult", 3.0)
        )
        self._stop_loss_pct: float = p.get("stop_loss_pct", 0.0)
        self._rsi_adaptive_profit: bool = p.get("rsi_adaptive_profit", True)

        self._bars: list[Bar] = []
        self._close_values: list[float] = []
        self._high_values: list[float] = []
        self._low_values: list[float] = []
        self._volume_values: list[float] = []
        self._ema_fast_value: float | None = None
        self._ema_slow_value: float | None = None
        self._macd_signal_value: float | None = None
        self._macd_hist_value: float | None = None
        self._true_range_values: list[float] = []
        self._atr_values: list[float | None] = []
        self._last_entry_conditions: int = 0
        # Position tracking for on_bar exit mechanisms
        self._in_position: bool = False
        self._entry_price: float = 0.0
        self._bars_since_entry: int = 0
        self._highest_since_entry: float = 0.0
        self._max_bars = (
            max(
                self._slow_period,
                self._macd_slow,
                self._rsi_period,
                self._atr_period,
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

        if len(self._bars) < self._slow_period + self._macd_signal:
            return

        entry, exit_ = self._latest_signal()
        if entry and not self._in_position:
            conditions_met = self._last_entry_conditions
            strength = min(0.4 + 0.15 * conditions_met, 0.9)
            ctx.emit_signal(
                bar.symbol,
                Direction.LONG,
                strength=strength,
                price=bar.close,
                strategy_id=self.name,
            )
            self._in_position = True
            self._entry_price = bar.close
            # _bars_since_entry is incremented at the START of _check_position_exits
            # on the NEXT bar. Starting at 0 and skipping the exit check on the
            # entry bar itself avoids an off-by-one where max_holding_bars=N would
            # actually close after N-1 bars (CORR-L2) — entry bar is the open,
            # not the first held bar.
            self._bars_since_entry = 0
            self._highest_since_entry = bar.high
        elif exit_ and self._in_position:
            # Exit: use FLAT to close position, not SHORT to open new one
            ctx.emit_signal(
                bar.symbol,
                Direction.FLAT,
                strength=0.5,
                price=bar.close,
                strategy_id=self.name,
            )
            self._in_position = False

        # on_bar exit mechanisms: profit target + max holding + trailing stop.
        # Skip on the entry bar — a position opened this bar cannot also be
        # exited this bar by a holding-period/profit-target rule (mirrors the
        # generate_signals profit_target_exit loop, which `continue`s on the
        # entry bar before evaluating exits).
        if self._in_position and self._bars_since_entry > 0:
            self._check_position_exits(ctx, bar)

    def _latest_signal(self) -> tuple[bool, bool]:
        """Compute the last signal without rebuilding a DataFrame."""
        close_values, high_values, low_values, volume_values = self._runtime_values()
        last_idx = len(close_values) - 1

        fast_ma = rolling_mean_at(close_values, last_idx, self._fast_period)
        slow_ma = rolling_mean_at(close_values, last_idx, self._slow_period)
        volume_ma = rolling_mean_at(volume_values, last_idx, self._volume_period)
        rsi = simple_rsi_last(close_values, self._rsi_period)
        if fast_ma is None or slow_ma is None or volume_ma is None or rsi is None:
            self._last_entry_conditions = 0
            return False, False

        if self._runtime_state_is_current() and self._macd_hist_value is not None:
            macd_hist = self._macd_hist_value
            atr_values = self._atr_values
        else:
            ema_fast = ewm_series(close_values, self._macd_fast)
            ema_slow = ewm_series(close_values, self._macd_slow)
            macd_line = [fast - slow for fast, slow in zip(ema_fast, ema_slow, strict=False)]
            macd_signal = ewm_series(macd_line, self._macd_signal)
            if not macd_signal:
                self._last_entry_conditions = 0
                return False, False
            macd_hist = macd_line[-1] - macd_signal[-1]
            atr_values = rolling_average_true_ranges(
                high_values,
                low_values,
                close_values,
                self._atr_period,
            )

        atr = atr_values[-1]
        atr_cap_mean = rolling_mean_optional_at(atr_values, last_idx, self._slow_period)
        if atr is None or atr_cap_mean is None:
            self._last_entry_conditions = 0
            return False, False
        atr_cap = atr_cap_mean * self._atr_multiplier

        vol_ok = volume_values[-1] > volume_ma * self._volume_threshold
        atr_ok = atr < atr_cap
        trend_up = fast_ma > slow_ma and macd_hist > 0
        trend_down = fast_ma < slow_ma and macd_hist < 0
        entry_count = int(trend_up) + int(rsi < self._rsi_overbought) + int(vol_ok) + int(atr_ok)
        entry = entry_count >= self._min_conditions
        exit_count = int(trend_down) + int(rsi > self._rsi_oversold) + int(atr_ok)
        exit_ = exit_count >= max(self._min_conditions - 1, 2)  # exit without vol_ok
        self._last_entry_conditions = entry_count if entry else 0
        return entry, exit_

    def _append_runtime_state(self, bar: Bar) -> None:
        previous_close = self._close_values[-2] if len(self._close_values) > 1 else None
        true_range = true_range_value(bar.high, bar.low, bar.close, previous_close)
        self._true_range_values.append(true_range)
        last_idx = len(self._true_range_values) - 1
        self._atr_values.append(
            rolling_mean_at(self._true_range_values, last_idx, self._atr_period)
        )

        self._ema_fast_value = ewm_next(self._ema_fast_value, bar.close, self._macd_fast)
        self._ema_slow_value = ewm_next(self._ema_slow_value, bar.close, self._macd_slow)
        macd_line = self._ema_fast_value - self._ema_slow_value
        self._macd_signal_value = ewm_next(
            self._macd_signal_value,
            macd_line,
            self._macd_signal,
        )
        self._macd_hist_value = macd_line - self._macd_signal_value

    def _runtime_state_is_current(self) -> bool:
        return len(self._close_values) == len(self._bars) and len(self._atr_values) == len(
            self._bars
        )

    def _runtime_values(self) -> tuple[list[float], list[float], list[float], list[float]]:
        if len(self._close_values) == len(self._bars):
            return self._close_values, self._high_values, self._low_values, self._volume_values
        return closes(self._bars), highs(self._bars), lows(self._bars), volumes(self._bars)

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Vectorized signal generation (research/backtest API).

        .. note:: This is a stateless research API and does NOT apply regime
            gating. The event-driven ``on_bar`` path (TradingSession) gates the
            strategy by ``required_regime`` via MarketRegimeDetector (ADX>=25 for
            "trending") before calling ``on_bar`` — so entries computed here on
            non-regime bars are traded in backtest but gated out of live/paper.
            This is an intentional two-layer design (regime = macro market-state
            gate via ADX strength; entry = micro signal via MA direction), NOT a
            bug (ISS-20260720-001, resolved as design-property). For live-faithful
            validation use paper-on_bar replay, not this vectorized path.
        """
        if len(df) < self._slow_period + self._macd_signal:
            empty = pd.Series(False, index=df.index)
            return empty, empty

        close = df["close"]
        high = df.get("high", close)
        low = df.get("low", close)
        volume = df.get("volume", pd.Series(1.0, index=df.index))

        fast_ma = close.rolling(self._fast_period).mean()
        slow_ma = close.rolling(self._slow_period).mean()

        ema_fast = close.ewm(span=self._macd_fast, adjust=False).mean()
        ema_slow = close.ewm(span=self._macd_slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        macd_signal = macd_line.ewm(span=self._macd_signal, adjust=False).mean()
        macd_hist = macd_line - macd_signal

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(self._rsi_period).mean()
        avg_loss = loss.rolling(self._rsi_period).mean()
        rs = avg_gain / avg_loss.replace(0, 1e-10)
        rsi = 100 - (100 / (1 + rs))

        tr = pd.concat(
            [
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(self._atr_period).mean()
        atr_cap = atr.rolling(self._slow_period).mean() * self._atr_multiplier

        vol_ma = volume.rolling(self._volume_period).mean()
        vol_ok = volume > vol_ma * self._volume_threshold

        trend_up = (fast_ma > slow_ma) & (macd_hist > 0)
        trend_down = (fast_ma < slow_ma) & (macd_hist < 0)
        rsi_ok_long = rsi < self._rsi_overbought
        rsi_ok_short = rsi > self._rsi_oversold
        atr_ok = atr < atr_cap

        long_count = (
            trend_up.astype(int) + rsi_ok_long.astype(int) + vol_ok.astype(int) + atr_ok.astype(int)
        )
        # Exit mirror of _latest_signal: exits do NOT require volume confirmation
        # (entry does). Exit count excludes vol_ok and uses a relaxed threshold
        # (min_conditions - 1) so exits fire on the same bar in both the
        # vectorized (generate_signals) and incremental (on_bar/_latest_signal)
        # paths — ISS-20260613-006 parity. Previously exits used short_count
        # (with vol_ok, threshold min_conditions), which systematically diverged
        # from _latest_signal (no vol_ok, threshold min_conditions-1).
        exit_count = trend_down.astype(int) + rsi_ok_short.astype(int) + atr_ok.astype(int)
        entries = long_count >= self._min_conditions
        exits = exit_count >= max(self._min_conditions - 1, 2)

        # Profit target exit (LONG direction only — trend_following entries are LONG)
        effective_pct = self._profit_take_pct
        if self._rsi_adaptive_profit:
            # RSI-adaptive: tighter target when overbought at entry.
            # Per-bar effective pct using ONLY the RSI value at each entry bar
            # (forward-filled while in position) — never the RSI of future
            # entry bars, which would be a look-ahead bias.
            rsi_at_entry = rsi.where(entries)
            rsi_at_entry = rsi_at_entry.ffill()
            tight = self._profit_take_pct * 0.8
            wide = self._profit_take_pct * 1.2
            effective_pct_series = effective_pct * pd.Series(1.0, index=close.index)
            overbought = rsi_at_entry > 70
            oversold = rsi_at_entry < 30
            effective_pct_series = effective_pct_series.where(~overbought, tight)
            effective_pct_series = effective_pct_series.where(~oversold, wide)
            profit_exits = profit_target_exit_series(
                close, entries, effective_pct_series, self._max_holding_bars, direction=1
            )
        else:
            profit_exits = profit_target_exit(
                close, entries, effective_pct, self._max_holding_bars, direction=1
            )

        # Trailing stop exit — track highest HIGH for LONG positions
        trailing_atr = atr
        highest = high.copy()
        in_pos = False
        for i in range(len(close)):
            if entries.iloc[i] and not in_pos:
                in_pos = True
            if in_pos:
                highest.iloc[i] = max(
                    float(high.iloc[i]),
                    float(highest.iloc[i - 1]) if i > 0 else float(high.iloc[i]),
                )
                if exits.iloc[i] or profit_exits.iloc[i]:
                    in_pos = False
            if not in_pos:
                highest.iloc[i] = float(high.iloc[i])
        trailing_exits = close < highest - trailing_atr * self._trailing_stop_atr_mult

        exits = exits | profit_exits | trailing_exits

        return entries.fillna(False), exits.fillna(False)

    def _check_position_exits(self, ctx: StrategyContext, bar: Bar) -> None:
        """Check profit target, trailing stop, and max holding exits in on_bar path."""
        if not self._in_position:
            return

        self._bars_since_entry += 1
        self._highest_since_entry = max(self._highest_since_entry, bar.high)

        # Profit target exit (LONG: close >= entry * (1+pct))
        target_price = self._entry_price * (1.0 + self._profit_take_pct)
        if bar.close >= target_price:
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

        # Trailing stop exit (LONG: close < highest - ATR*mult)
        if self._atr_values and self._atr_values[-1] is not None:
            trailing_level = (
                self._highest_since_entry - self._atr_values[-1] * self._trailing_stop_atr_mult
            )
            if bar.close < trailing_level:
                ctx.emit_signal(
                    bar.symbol, Direction.FLAT, strength=0.5, price=bar.close, strategy_id=self.name
                )
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

    def get_required_indicators(self) -> list[dict[str, Any]]:
        return [
            {"name": "sma", "params": {"period": self._fast_period}},
            {"name": "sma", "params": {"period": self._slow_period}},
            {
                "name": "macd",
                "params": {
                    "fast": self._macd_fast,
                    "slow": self._macd_slow,
                    "signal": self._macd_signal,
                },
            },
            {"name": "rsi", "params": {"period": self._rsi_period}},
            {"name": "atr", "params": {"period": self._atr_period}},
        ]
