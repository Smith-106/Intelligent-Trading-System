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
        """Return and clear all queued signals."""
        signals = self._signals[:]
        self._signals.clear()
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
