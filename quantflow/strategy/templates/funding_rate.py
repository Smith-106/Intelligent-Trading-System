"""Funding rate strategy — crypto-specific signal using funding rate extremes + open interest."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyBase, StrategyContext
from quantflow.strategy.templates._runtime import profit_target_exit

logger = logging.getLogger(__name__)


class FundingRateStrategy(StrategyBase):
    """Funding rate mean-reversion strategy.

    Crypto perpetual swaps charge a funding rate every 8h.
    Extreme rates signal overcrowded positions → mean reversion.

    Entry:
    - Long when funding_rate < -threshold (shorts overcrowded → price likely up)
    - Short when funding_rate > +threshold (longs overcrowded → price likely down)
    - Open interest confirmation: OI change aligns with the crowd direction

    Exit:
    - Funding rate returns to neutral zone (between ±exit_threshold)
    - OI reversal signal
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(name="funding_rate", params=params)
        self.required_regime = "mean_reversion"
        p = self._params
        self._entry_threshold = p.get("entry_threshold", 0.001)
        self._exit_threshold = p.get("exit_threshold", 0.0003)
        self._oi_lookback = p.get("oi_lookback", 3)
        self._oi_change_threshold = p.get("oi_change_threshold", 0.05)
        self._rate_ema_period = p.get("rate_ema_period", 8)
        # B5 ablation knobs — defaults preserve B3/B4 sealed behavior
        self._use_rate_ema = bool(p.get("use_rate_ema", True))
        self._require_oi_confirmation = bool(p.get("require_oi_confirmation", True))
        self._cooldown_bars = p.get("cooldown_bars", 6)
        self._profit_take_pct: float = p.get("take_profit_pct", p.get("profit_take_pct", 0.02))
        self._max_holding_bars: int = p.get("max_holding_bars", 8)
        self._stop_loss_pct: float = p.get("stop_loss_pct", 0.0)

        self._bars: list[Bar] = []
        self._funding_rates: list[float] = []
        self._open_interests: list[float] = []
        self._cooldown_counter = 0
        self._max_bars = 200
        # Position tracking for on_bar exit mechanisms
        self._in_position: bool = False
        self._entry_direction: Direction | None = None
        self._entry_price: float = 0.0
        self._bars_since_entry: int = 0
        # T-s2-04: live-feed freshness gate (fail-closed, entries only).
        # True by default — backtest and feed-disabled runs keep baseline
        # behavior; TradingSession sets it False when funding/OI data goes
        # stale (analyze F4 fail_closed contract: block NEW entries, never
        # exits, so an open position can still be closed on stale data).
        self._freshness_gate: bool = True

    def on_init(self, ctx: StrategyContext) -> None:
        ctx.params = self._params

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        self._bars.append(bar)
        if len(self._bars) > self._max_bars:
            self._bars = self._bars[-self._max_bars :]

        # Cooldown gates NEW entries only — never exits. Blocking exits during
        # the cooldown window would prevent stop/profit exits for up to
        # _cooldown_bars bars, leaving adverse positions un-closeable.
        in_cooldown = self._cooldown_counter > 0
        if in_cooldown:
            self._cooldown_counter -= 1

        min_bars = self._min_bars()
        if len(self._bars) < min_bars or len(self._funding_rates) < min_bars:
            return

        df = self._build_signal_df()
        if df.empty:
            return

        entries, exits = self.generate_signals(df)
        if entries.empty:
            return

        last_idx = len(entries) - 1
        symbol = bar.symbol

        if exits.iloc[last_idx] and self._in_position:
            ctx.emit_signal(
                symbol, Direction.FLAT, strength=0.5, price=bar.close, strategy_id=self.name
            )
            self._in_position = False
            return

        if in_cooldown:
            return

        if entries.iloc[last_idx] and not self._in_position:
            # T-s2-04 fail-closed gate: stale/missing funding/OI feed blocks
            # NEW entries only — exits above (FLAT) and _check_position_exits
            # below remain unaffected by design.
            if not self._freshness_gate:
                logger.info(
                    "funding_rate entry skipped: feed stale/missing (fail-closed) %s", symbol
                )
            else:
                rate = self._funding_rates[-1] if self._funding_rates else 0.0
                direction = Direction.LONG if rate < -self._entry_threshold else Direction.SHORT
                ctx.emit_signal(
                    symbol, direction, strength=0.7, price=bar.close, strategy_id=self.name
                )
                self._cooldown_counter = self._cooldown_bars
                self._in_position = True
                self._entry_direction = direction
                self._entry_price = bar.close
                self._bars_since_entry = 0

        # on_bar exit mechanisms
        self._check_position_exits(ctx, bar)

    def update_funding_rate(self, rate: float) -> None:
        """Feed a new funding rate observation (called externally by data layer)."""
        self._funding_rates.append(rate)
        if len(self._funding_rates) > self._max_bars:
            self._funding_rates = self._funding_rates[-self._max_bars :]

    def set_freshness_gate(self, fresh: bool) -> None:
        """T-s2-04: set the live-feed freshness gate.

        ``fresh=False`` blocks NEW entry signals at on_bar time (fail-closed);
        exit/FLAT signals are never gated so open positions stay closeable.
        Called by TradingSession based on meta-feed freshness state.
        """
        self._freshness_gate = bool(fresh)

    def update_open_interest(self, oi: float) -> None:
        """Feed a new open interest observation (called externally by data layer)."""
        self._open_interests.append(oi)
        if len(self._open_interests) > self._max_bars:
            self._open_interests = self._open_interests[-self._max_bars :]

    def _min_bars(self) -> int:
        """Warmup bars; shorter when EMA/OI filters are ablated (B5)."""
        need = 1
        if self._use_rate_ema:
            need = max(need, int(self._rate_ema_period) * 2)
        if self._require_oi_confirmation:
            need = max(need, int(self._oi_lookback) + 1)
        return max(1, need)

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        min_bars = self._min_bars()
        if len(df) < min_bars:
            empty = pd.Series(False, index=df.index)
            return empty, empty

        funding_rate = df.get("funding_rate", pd.Series(0.0, index=df.index))
        open_interest = df.get("open_interest", pd.Series(0.0, index=df.index))

        # Rate level: EMA smooth (B3/B4 default) or raw (B5 EMA-off)
        if self._use_rate_ema:
            rate_level = funding_rate.ewm(span=self._rate_ema_period).mean()
        else:
            rate_level = funding_rate.astype(float)

        # Extreme funding rate signals
        long_signal = rate_level < -self._entry_threshold  # shorts crowded → go long
        short_signal = rate_level > self._entry_threshold  # longs crowded → go short

        if self._require_oi_confirmation:
            # Open interest confirmation: OI increasing in crowded direction
            oi_change = open_interest.pct_change(self._oi_lookback)
            oi_rising = oi_change > self._oi_change_threshold
            oi_falling = oi_change < -self._oi_change_threshold
            long_entry = long_signal & oi_rising
            short_entry = short_signal & oi_rising
            oi_reversal = (long_signal & oi_falling) | (short_signal & oi_falling)
        else:
            # B5 OI-off: pure rate extreme; no OI filter on entry/exit
            long_entry = long_signal
            short_entry = short_signal
            oi_reversal = pd.Series(False, index=df.index)

        entries = long_entry | short_entry

        # Exit: rate returns to neutral (+ optional OI reversal when OI on)
        neutral_zone = rate_level.abs() < self._exit_threshold
        exits = neutral_zone | oi_reversal

        # Profit target exit
        close = df["close"]
        profit_exits = profit_target_exit(
            close, entries, self._profit_take_pct, self._max_holding_bars
        )
        exits = exits | profit_exits

        return entries.fillna(False), exits.fillna(False)

    def _check_position_exits(self, ctx: StrategyContext, bar: Bar) -> None:
        """Check profit target and max holding exits in on_bar path."""
        if not self._in_position:
            return

        self._bars_since_entry += 1

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

    def _build_signal_df(self) -> pd.DataFrame:
        if not self._bars:
            return pd.DataFrame()
        n = min(len(self._bars), len(self._funding_rates), len(self._open_interests))
        if n == 0:
            return pd.DataFrame()
        data = {
            "timestamp": [b.timestamp for b in self._bars[:n]],
            "close": [b.close for b in self._bars[:n]],
            "funding_rate": self._funding_rates[:n],
            "open_interest": self._open_interests[:n],
        }
        return pd.DataFrame(data)

    def get_required_indicators(self) -> list[dict[str, Any]]:
        return [
            {"name": "funding_rate", "params": {"ema_period": self._rate_ema_period}},
            {"name": "open_interest", "params": {"lookback": self._oi_lookback}},
        ]
