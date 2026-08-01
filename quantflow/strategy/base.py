"""Strategy base — abstract interface for all trading strategies."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from quantflow.common.models import Bar, Direction, Signal

logger = logging.getLogger(__name__)


class StrategyContext:
    """Runtime context for a strategy within a trading session.

    Accumulates signals generated during on_bar() and flushes them
    to the risk/execution pipeline.
    """

    def __init__(self) -> None:
        self._signals: list[Signal] = []
        self._data: pd.DataFrame | None = None
        self._params: dict[str, Any] = {}

    def emit_signal(
        self,
        symbol: str,
        direction: Direction,
        strength: float = 1.0,
        price: float = 0.0,
        strategy_id: str = "",
    ) -> None:
        """Queue a signal for processing."""
        self._signals.append(
            Signal(
                symbol=symbol,
                direction=direction,
                strength=max(0.0, min(strength, 1.0)),
                price=price,
                strategy_id=strategy_id,
            )
        )

    def flush_signals(self) -> list[Signal]:
        """Return and clear all queued signals (atomic swap).

        Uses reference swap rather than copy+clear so the operation is a
        single bytecode-level assignment under the GIL — safe when on_bar
        runs in a worker thread (asyncio.to_thread) and flush is called
        from the main coroutine after the future completes (M4-1.1).
        """
        signals, self._signals = self._signals, []
        return signals

    @property
    def data(self) -> pd.DataFrame | None:
        return self._data

    @data.setter
    def data(self, value: pd.DataFrame) -> None:
        self._data = value

    @property
    def params(self) -> dict[str, Any]:
        return self._params

    @params.setter
    def params(self, value: dict[str, Any]) -> None:
        self._params = value


class StrategyBase(ABC):
    """Abstract base class for all trading strategies.

    Subclasses must implement on_init(), on_bar(), and generate_signals().
    For event-driven mode, use emit_signal() in on_bar() instead of
    generate_signals().
    """

    def __init__(self, name: str = "", params: dict[str, Any] | None = None) -> None:
        self.name = name or self.__class__.__name__
        self._params = params or {}
        self.required_regime: str = "any"  # "trending", "mean_reversion", "any"

    @property
    def params(self) -> dict[str, Any]:
        return self._params

    @params.setter
    def params(self, value: dict[str, Any]) -> None:
        self._params = value

    def on_init(self, ctx: StrategyContext) -> None:
        """Called once at strategy initialization. Override to set up indicators."""

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        """Called on each new bar in event-driven mode.

        Override this for live/paper trading. Use ctx.emit_signal()
        to generate signals.
        """

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Generate entry/exit signals from a DataFrame (vectorized mode).

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV data with computed indicators.

        Returns
        -------
        tuple[pd.Series, pd.Series]
            (entries, exits) boolean Series aligned to df index.

        Note
        ----
        ``generate_signals`` (stateless research/backtest API) and ``on_bar``
        (stateful live/paper path) are **best-effort parity**, NOT a strict
        guarantee. Two documented divergence classes exist:

        1. **Regime gate**: ``on_bar`` is gated by ``required_regime`` via
           MarketRegimeDetector (e.g. ADX>=25 for "trending"); the vectorized
           path is not. So backtest trades a superset of live/paper entries.
           This is an intentional two-layer design (ISS-20260720-001,
           resolved as design-property): regime = macro market-state gate,
           entry = micro MA-direction signal. For live-faithful validation use
           paper-on_bar replay, not this vectorized path.
        2. **Indicator formula**: a strategy may compute an indicator
           differently in the two paths (e.g. trend_following uses SMA-based
           RSI in ``generate_signals`` and a matching incremental RSI in
           ``on_bar``). Each strategy must document its own divergence points.

        Implementers SHOULD keep the two paths as close as possible and
        document any remaining divergence in the ``generate_signals`` docstring.
        """
        ...

    def on_tick(self, ctx: StrategyContext, tick: Any) -> None:
        """Handle a real-time tick event.

        Default: no action. Override for tick-level logic (e.g., HFT).

        Args:
            ctx: Strategy context for signal emission.
            tick: Tick data (symbol, price, volume, timestamp, bid, ask).
        """

    def get_required_indicators(self) -> list[dict[str, Any]]:
        """Return list of indicator configs needed by this strategy.

        Override to declare dependencies for the IndicatorEngine.
        """
        return []
