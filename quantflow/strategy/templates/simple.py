"""Jesse-style thin strategy template (W16 DX).

Subclass and override ``should_long`` / ``should_short`` / ``should_exit_long`` /
``should_exit_short``. Both ``on_bar`` (event) and ``generate_signals``
(vectorized research) share the same boolean rules so research→paper
divergence is minimized for this template.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyBase, StrategyContext

logger = logging.getLogger(__name__)


class SimpleStrategy(StrategyBase):
    """Minimal plugin surface for custom research strategies.

    Default implementation is a long-only SMA crossover (fast > slow enter;
    fast < slow exit). Override hooks for custom logic without multi-filter
    boilerplate from production templates.
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(name="simple", params=params)
        self.required_regime = str(self._params.get("required_regime", "any"))
        self._fast = int(self._params.get("fast_period", 10))
        self._slow = int(self._params.get("slow_period", 30))
        self._closes: list[float] = []
        self._max_bars = max(self._slow, self._fast) + 50
        self._in_long = False
        self._in_short = False

    def on_init(self, ctx: StrategyContext) -> None:
        ctx.params = self._params

    # --- hooks (override these) -------------------------------------------------

    def should_long(self, closes: list[float] | pd.Series) -> bool:
        """Return True to open / hold long intent on the latest bar."""
        return self._sma_cross_up(closes)

    def should_short(self, closes: list[float] | pd.Series) -> bool:
        """Return True to open short (default: never — long-only)."""
        return False

    def should_exit_long(self, closes: list[float] | pd.Series) -> bool:
        return self._sma_cross_down(closes)

    def should_exit_short(self, closes: list[float] | pd.Series) -> bool:
        return self._sma_cross_up(closes)

    # --- event path -------------------------------------------------------------

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        self._closes.append(float(bar.close))
        if len(self._closes) > self._max_bars:
            self._closes = self._closes[-self._max_bars :]
        if len(self._closes) < self._slow:
            return

        if not self._in_long and not self._in_short and self.should_long(self._closes):
            ctx.emit_signal(
                bar.symbol,
                Direction.LONG,
                strength=0.6,
                price=bar.close,
                strategy_id=self.name,
            )
            self._in_long = True
            return

        if not self._in_long and not self._in_short and self.should_short(self._closes):
            ctx.emit_signal(
                bar.symbol,
                Direction.SHORT,
                strength=0.6,
                price=bar.close,
                strategy_id=self.name,
            )
            self._in_short = True
            return

        if self._in_long and self.should_exit_long(self._closes):
            ctx.emit_signal(
                bar.symbol,
                Direction.FLAT,
                strength=0.5,
                price=bar.close,
                strategy_id=self.name,
            )
            self._in_long = False
            return

        if self._in_short and self.should_exit_short(self._closes):
            ctx.emit_signal(
                bar.symbol,
                Direction.FLAT,
                strength=0.5,
                price=bar.close,
                strategy_id=self.name,
            )
            self._in_short = False

    # --- vectorized path --------------------------------------------------------

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        if df is None or len(df) == 0:
            empty = pd.Series(dtype=bool)
            return empty, empty
        close = df["close"] if "close" in df.columns else df.iloc[:, 3]
        entries = pd.Series(False, index=df.index)
        exits = pd.Series(False, index=df.index)
        in_long = False
        in_short = False
        for i in range(len(df)):
            window = close.iloc[: i + 1]
            if len(window) < self._slow:
                continue
            if not in_long and not in_short and self.should_long(window):
                entries.iloc[i] = True
                in_long = True
            elif not in_long and not in_short and self.should_short(window):
                entries.iloc[i] = True
                in_short = True
            elif in_long and self.should_exit_long(window):
                exits.iloc[i] = True
                in_long = False
            elif in_short and self.should_exit_short(window):
                exits.iloc[i] = True
                in_short = False
        return entries, exits

    # --- helpers ----------------------------------------------------------------

    def _sma(self, closes: list[float] | pd.Series, period: int) -> float | None:
        if isinstance(closes, pd.Series):
            if len(closes) < period:
                return None
            return float(closes.iloc[-period:].mean())
        if len(closes) < period:
            return None
        return float(sum(closes[-period:]) / period)

    def _sma_cross_up(self, closes: list[float] | pd.Series) -> bool:
        fast = self._sma(closes, self._fast)
        slow = self._sma(closes, self._slow)
        if fast is None or slow is None:
            return False
        return fast > slow

    def _sma_cross_down(self, closes: list[float] | pd.Series) -> bool:
        fast = self._sma(closes, self._fast)
        slow = self._sma(closes, self._slow)
        if fast is None or slow is None:
            return False
        return fast < slow
