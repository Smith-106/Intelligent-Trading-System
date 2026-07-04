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

    def consolidate_signals(
        self,
        signals: list[Signal],
        strategy_hit_rates: dict[str, float] | None = None,
    ) -> Signal | None:
        """Consolidate multiple signals for the same symbol.

        Aggregates direction by strength-weighted vote and averages strength.
        Weight = signal.strength * strategy_hit_rate (default 0.5 for unknown).
        """
        if not signals:
            return None

        # Strength-weighted direction vote
        hit_rates = strategy_hit_rates or {}
        weights = [s.strength * hit_rates.get(s.strategy_id, 0.5) for s in signals]
        net = sum(s.direction.value * w for s, w in zip(signals, weights, strict=True))

        if net > 0:
            direction = Direction.LONG
        elif net < 0:
            direction = Direction.SHORT
        else:
            return None  # Conflicting signals cancel out

        total_weight = sum(weights)
        avg_strength = total_weight / len(signals) if total_weight > 0 else 0.0

        return Signal(
            symbol=signals[0].symbol,
            direction=direction,
            strength=avg_strength,
            price=signals[0].price,
            # Deterministic, sorted compound key. A plain ``set(...)`` join
            # produced a non-deterministic ordering, so the same inputs could
            # yield different strategy_id strings across bars — and the
            # comma-joined key never matched a single-strategy risk budget,
            # silently bypassing per-strategy limits (see risk_engine).
            strategy_id=",".join(sorted({s.strategy_id for s in signals})),
        )
