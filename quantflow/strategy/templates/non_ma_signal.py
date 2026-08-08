"""Non-MA signal families — fixed-parameter alternatives to MA crossover.

Three families (no Optuna knobs in the research protocol):

- ``donchian``: price-channel breakout (prior N-bar high / M-bar low)
- ``volume_roc``: volume surge + positive rate-of-change momentum
- ``rsi_thrust``: RSI cross above level with volume confirmation

None of these use MA crossover as the primary entry logic.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyBase, StrategyContext

logger = logging.getLogger(__name__)

FAMILIES = frozenset({"donchian", "volume_roc", "rsi_thrust"})


class NonMaSignalStrategy(StrategyBase):
    """Event-driven + vectorized non-MA signal strategy."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(name="non_ma_signal", params=params)
        # Align with trend templates so nested/regime gate path is comparable.
        self.required_regime = "trending"
        p = self._params
        family = str(p.get("signal_family", "donchian")).lower()
        if family not in FAMILIES:
            raise ValueError(
                f"Unknown signal_family {family!r}; expected one of {sorted(FAMILIES)}"
            )
        self._family = family

        # Donchian
        self._channel_period = int(p.get("channel_period", 20))
        self._exit_period = int(p.get("exit_period", 10))
        # Volume-ROC
        self._roc_period = int(p.get("roc_period", 12))
        self._vol_period = int(p.get("vol_period", 20))
        self._vol_threshold = float(p.get("vol_threshold", 1.5))
        # RSI thrust
        self._rsi_period = int(p.get("rsi_period", 14))
        self._rsi_level = float(p.get("rsi_level", 50.0))
        self._rsi_vol_threshold = float(p.get("rsi_vol_threshold", p.get("vol_threshold", 1.2)))
        # Shared risk exits
        self._max_holding_bars = int(p.get("max_holding_bars", 48 if family == "donchian" else 36))
        self._stop_loss_pct = float(p.get("stop_loss_pct", 0.0))

        self._bars: list[Bar] = []
        self._close_values: list[float] = []
        self._high_values: list[float] = []
        self._low_values: list[float] = []
        self._volume_values: list[float] = []
        self._in_position = False
        self._entry_price = 0.0
        self._bars_since_entry = 0
        self._prev_rsi: float | None = None
        self._max_bars = (
            max(
                self._channel_period,
                self._exit_period,
                self._roc_period,
                self._vol_period,
                self._rsi_period,
            )
            + 50
        )

    def on_init(self, ctx: StrategyContext) -> None:
        ctx.params = self._params

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        self._bars.append(bar)
        self._close_values.append(bar.close)
        self._high_values.append(bar.high)
        self._low_values.append(bar.low)
        self._volume_values.append(bar.volume)
        if len(self._bars) > self._max_bars:
            self._bars = self._bars[-self._max_bars :]
            self._close_values = self._close_values[-self._max_bars :]
            self._high_values = self._high_values[-self._max_bars :]
            self._low_values = self._low_values[-self._max_bars :]
            self._volume_values = self._volume_values[-self._max_bars :]

        need = self._warmup()
        if len(self._close_values) < need:
            return

        entry, exit_ = self._latest_signal()
        if entry and not self._in_position:
            ctx.emit_signal(
                bar.symbol,
                Direction.LONG,
                strength=0.7,
                price=bar.close,
                strategy_id=self.name,
            )
            self._in_position = True
            self._entry_price = bar.close
            self._bars_since_entry = 0
        elif exit_ and self._in_position:
            ctx.emit_signal(
                bar.symbol,
                Direction.FLAT,
                strength=0.5,
                price=bar.close,
                strategy_id=self.name,
            )
            self._in_position = False

        if self._in_position and self._bars_since_entry > 0:
            self._bars_since_entry += 1
            if self._stop_loss_pct > 0 and bar.close <= self._entry_price * (
                1.0 - self._stop_loss_pct
            ):
                ctx.emit_signal(
                    bar.symbol,
                    Direction.FLAT,
                    strength=0.5,
                    price=bar.close,
                    strategy_id=self.name,
                )
                self._in_position = False
                return
            if self._bars_since_entry >= self._max_holding_bars:
                ctx.emit_signal(
                    bar.symbol,
                    Direction.FLAT,
                    strength=0.5,
                    price=bar.close,
                    strategy_id=self.name,
                )
                self._in_position = False
        elif self._in_position:
            # Entry bar: start counting next bar.
            self._bars_since_entry = 1

    def _warmup(self) -> int:
        if self._family == "donchian":
            return max(self._channel_period, self._exit_period) + 1
        if self._family == "volume_roc":
            return max(self._roc_period, self._vol_period) + 1
        return max(self._rsi_period, self._vol_period) + 2

    def _latest_signal(self) -> tuple[bool, bool]:
        c = self._close_values
        h = self._high_values
        low_vals = self._low_values
        v = self._volume_values
        i = len(c) - 1
        if self._family == "donchian":
            return self._donchian_latest(c, h, low_vals, i)
        if self._family == "volume_roc":
            return self._volume_roc_latest(c, v, i)
        return self._rsi_thrust_latest(c, v, i)

    def _donchian_latest(
        self, c: list[float], h: list[float], low_vals: list[float], i: int
    ) -> tuple[bool, bool]:
        n, m = self._channel_period, self._exit_period
        if i < n:
            return False, False
        prior_high = max(h[i - n : i])  # exclude current
        if i >= m:
            prior_low = min(low_vals[i - m : i])
        elif i > 0:
            prior_low = min(low_vals[:i])
        else:
            prior_low = low_vals[i]
        entry = c[i] > prior_high
        exit_ = c[i] < prior_low
        return entry, exit_

    def _volume_roc_latest(self, c: list[float], v: list[float], i: int) -> tuple[bool, bool]:
        rp, vp = self._roc_period, self._vol_period
        if i < max(rp, vp):
            return False, False
        roc = (c[i] / c[i - rp] - 1.0) if c[i - rp] != 0 else 0.0
        vol_ma = sum(v[i - vp + 1 : i + 1]) / vp
        vol_ratio = v[i] / vol_ma if vol_ma > 0 else 0.0
        entry = roc > 0.0 and vol_ratio >= self._vol_threshold
        exit_ = roc < 0.0
        return entry, exit_

    def _rsi_thrust_latest(self, c: list[float], v: list[float], i: int) -> tuple[bool, bool]:
        if i < max(self._rsi_period, self._vol_period) + 1:
            return False, False
        rsi_now = self._rsi_at(c, i)
        rsi_prev = self._rsi_at(c, i - 1)
        if rsi_now is None or rsi_prev is None:
            return False, False
        vol_ma = sum(v[i - self._vol_period + 1 : i + 1]) / self._vol_period
        vol_ratio = v[i] / vol_ma if vol_ma > 0 else 0.0
        cross_up = rsi_prev < self._rsi_level <= rsi_now
        cross_down = rsi_prev > self._rsi_level >= rsi_now
        entry = cross_up and vol_ratio >= self._rsi_vol_threshold
        exit_ = cross_down
        return entry, exit_

    def _rsi_at(self, c: list[float], idx: int) -> float | None:
        period = self._rsi_period
        if idx < period:
            return None
        gains = 0.0
        losses = 0.0
        for j in range(idx - period + 1, idx + 1):
            d = c[j] - c[j - 1]
            if d >= 0:
                gains += d
            else:
                losses -= d
        avg_gain = gains / period
        avg_loss = losses / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        if df.empty:
            empty = pd.Series(False, index=df.index)
            return empty, empty
        close = df["close"]
        high = df.get("high", close)
        low = df.get("low", close)
        volume = df.get("volume", pd.Series(1.0, index=df.index))

        if self._family == "donchian":
            prior_high = high.shift(1).rolling(self._channel_period).max()
            prior_low = low.shift(1).rolling(self._exit_period).min()
            entries = close > prior_high
            exits = close < prior_low
        elif self._family == "volume_roc":
            roc = close.pct_change(self._roc_period)
            vol_ma = volume.rolling(self._vol_period).mean()
            vol_ratio = volume / vol_ma.replace(0, 1e-12)
            entries = (roc > 0) & (vol_ratio >= self._vol_threshold)
            exits = roc < 0
        else:
            delta = close.diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.rolling(self._rsi_period).mean()
            avg_loss = loss.rolling(self._rsi_period).mean()
            rs = avg_gain / avg_loss.replace(0, 1e-10)
            rsi = 100 - (100 / (1 + rs))
            vol_ma = volume.rolling(self._vol_period).mean()
            vol_ratio = volume / vol_ma.replace(0, 1e-12)
            cross_up = (rsi.shift(1) < self._rsi_level) & (rsi >= self._rsi_level)
            cross_down = (rsi.shift(1) > self._rsi_level) & (rsi <= self._rsi_level)
            entries = cross_up & (vol_ratio >= self._rsi_vol_threshold)
            exits = cross_down

        # Max-holding exit overlay (vectorized approximate)
        hold_exit = pd.Series(False, index=df.index)
        in_pos = False
        held = 0
        for i in range(len(df)):
            if bool(entries.iloc[i]) and not in_pos:
                in_pos = True
                held = 0
            if in_pos:
                held += 1
                if held >= self._max_holding_bars:
                    hold_exit.iloc[i] = True
                    in_pos = False
                elif bool(exits.iloc[i]):
                    in_pos = False
        exits = exits | hold_exit
        return entries.fillna(False).astype(bool), exits.fillna(False).astype(bool)
