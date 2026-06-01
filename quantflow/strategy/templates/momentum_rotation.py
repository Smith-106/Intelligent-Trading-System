"""Momentum rotation strategy — cross-sectional momentum ranking for multi-symbol rotation."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyBase, StrategyContext

logger = logging.getLogger(__name__)


class MomentumRotationStrategy(StrategyBase):
    """Cross-sectional momentum rotation strategy.

    Ranks multiple symbols by momentum score and rotates into
    top-N performers. Crypto-specific: short lookback for fast regime shifts.

    Entry: symbol enters top-N momentum rank
    Exit: symbol drops out of top-N rank, or stop-loss triggered

    Note: generate_signals operates on a single symbol's DataFrame.
    For multi-symbol rotation, use generate_cross_sectional_signals()
    which accepts a dict of symbol → DataFrame.
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(name="momentum_rotation", params=params)
        p = self._params
        self._lookback = p.get("lookback", 20)
        self._top_n = p.get("top_n", 3)
        self._exit_rank_threshold = p.get("exit_rank_threshold", 5)
        self._stop_loss_pct = p.get("stop_loss_pct", 0.03)
        self._volume_period = p.get("volume_period", 20)
        self._rebalance_interval = p.get("rebalance_interval", 4)

        self._bars: list[Bar] = []
        self._max_bars = self._lookback + 50
        self._bar_count = 0
        self._current_positions: dict[str, float] = {}

    def on_init(self, ctx: StrategyContext) -> None:
        ctx.params = self._params

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        self._bars.append(bar)
        self._bar_count += 1
        if len(self._bars) > self._max_bars:
            self._bars = self._bars[-self._max_bars:]

        if len(self._bars) < self._lookback:
            return

        if self._bar_count % self._rebalance_interval != 0:
            return

        df = self._bars_to_df()
        if df.empty:
            return

        entries, exits = self.generate_signals(df)
        if entries.empty:
            return

        last_idx = len(entries) - 1
        symbol = bar.symbol

        if entries.iloc[last_idx]:
            ctx.emit_signal(symbol, Direction.LONG, strength=0.7, price=bar.close,
                            strategy_id=self.name)
            self._current_positions[symbol] = bar.close
        elif exits.iloc[last_idx]:
            ctx.emit_signal(symbol, Direction.FLAT, strength=0.5, price=bar.close,
                            strategy_id=self.name)
            self._current_positions.pop(symbol, None)

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        if len(df) < self._lookback:
            empty = pd.Series(False, index=df.index)
            return empty, empty

        close = df["close"]
        volume = df.get("volume", pd.Series(1.0, index=df.index))

        # Momentum score: rate of change over lookback
        momentum = close.pct_change(self._lookback)

        # Volume-weighted momentum
        vol_ma = volume.rolling(self._volume_period).mean()
        vol_weight = (volume / vol_ma.replace(0, 1e-10)).clip(0.5, 2.0)
        weighted_momentum = momentum * vol_weight

        # Simple entry: positive momentum above a threshold
        # (full ranking done in generate_cross_sectional_signals)
        entry_threshold = 0.02
        entries = weighted_momentum > entry_threshold

        # Exit: momentum turns negative or stop-loss
        momentum_negative = momentum < -0.01
        if self._stop_loss_pct > 0:
            peak = close.expanding().max()
            drawdown = (close - peak) / peak
            stop_hit = drawdown < -self._stop_loss_pct
        else:
            stop_hit = pd.Series(False, index=df.index)
        exits = momentum_negative | stop_hit

        return entries.fillna(False), exits.fillna(False)

    def generate_cross_sectional_signals(
        self,
        data: dict[str, pd.DataFrame],
    ) -> dict[str, tuple[pd.Series, pd.Series]]:
        """Generate rotation signals across multiple symbols.

        Parameters
        ----------
        data : dict[str, pd.DataFrame]
            Symbol → OHLCV DataFrame mapping.

        Returns
        -------
        dict[str, tuple[pd.Series, pd.Series]]
            Symbol → (entries, exits) boolean Series.
        """
        # Compute momentum scores for each symbol
        scores: dict[str, pd.Series] = {}
        for symbol, df in data.items():
            if len(df) < self._lookback:
                continue
            close = df["close"]
            momentum = close.pct_change(self._lookback)
            scores[symbol] = momentum

        if not scores:
            return {}

        # Rank by latest momentum
        latest_scores = {s: scores[s].iloc[-1] for s in scores}
        sorted_symbols = sorted(latest_scores.keys(), key=lambda s: latest_scores[s], reverse=True)
        top_set = set(sorted_symbols[:self._top_n])
        exit_set = set(sorted_symbols[self._exit_rank_threshold:])

        results: dict[str, tuple[pd.Series, pd.Series]] = {}
        for symbol, df in data.items():
            idx = df.index
            if symbol in top_set:
                entries = pd.Series(True, index=idx)
                exits = pd.Series(False, index=idx)
            elif symbol in exit_set:
                entries = pd.Series(False, index=idx)
                exits = pd.Series(True, index=idx)
            else:
                entries = pd.Series(False, index=idx)
                exits = pd.Series(False, index=idx)
            results[symbol] = (entries, exits)

        return results

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
            {"name": "momentum", "params": {"lookback": self._lookback}},
            {"name": "volume", "params": {"period": self._volume_period}},
        ]