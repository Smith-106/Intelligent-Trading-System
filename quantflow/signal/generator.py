"""Signal generator — create and aggregate trading signals."""

from __future__ import annotations

import logging

from quantflow.common.models import Direction, Signal

logger = logging.getLogger(__name__)


class SignalGenerator:
    """Generate and consolidate trading signals from strategy output."""

    def generate_signal(
        self,
        direction: Direction,
        strength: float = 1.0,
        symbol: str = "",
        price: float = 0.0,
        strategy_id: str = "",
    ) -> Signal | None:
        """Generate a trading signal.

        Parameters
        ----------
        direction : Direction
            LONG, SHORT, or FLAT.
        strength : float
            Signal strength [0, 1].
        symbol : str
            Trading symbol (e.g. "BTC/USDT").
        price : float
            Current price.
        strategy_id : str
            Source strategy identifier.

        Returns
        -------
        Signal or None
            Generated signal, or None if direction is FLAT.
        """
        if direction == Direction.FLAT:
            return None

        return Signal(
            symbol=symbol,
            direction=direction,
            strength=max(0.0, min(strength, 1.0)),
            price=price,
            strategy_id=strategy_id,
        )

    def consolidate_signals(self, signals: list[Signal]) -> Signal | None:
        """Consolidate multiple signals for the same symbol.

        Aggregates direction by net vote and averages strength.
        """
        if not signals:
            return None

        # Net direction from vote
        net = sum(s.direction.value for s in signals)
        if net > 0:
            direction = Direction.LONG
        elif net < 0:
            direction = Direction.SHORT
        else:
            return None  # Conflicting signals cancel out

        avg_strength = sum(s.strength for s in signals) / len(signals)

        return Signal(
            symbol=signals[0].symbol,
            direction=direction,
            strength=avg_strength,
            price=signals[0].price,
            strategy_id=",".join(set(s.strategy_id for s in signals)),
        )
