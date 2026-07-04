"""Market regime detector — ADX + volatility regime for strategy gating."""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass

import pandas as pd

from quantflow.indicators.trend import adx as adx_vectorized

logger = logging.getLogger(__name__)


@dataclass
class MarketRegime:
    """Current market regime classification."""

    adx: float = 0.0
    is_trending: bool = False
    bb_width_pct: float = 0.0  # BB width as % of middle band
    atr_percentile: float = 0.5  # 0-1 where 1 = highest ATR in lookback

    @property
    def regime_type(self) -> str:
        """Human-readable regime type."""
        if self.is_trending:
            return "trending"
        return "mean_reversion"


class MarketRegimeDetector:
    """Detect market regime using ADX + volatility metrics.

    Strategies perform differently in trending vs mean-reversion markets.
    This detector enables the TradingSession to gate strategies by regime:

    - ADX > trending_threshold: trending market — trend_following, volatility_breakout
    - ADX < trending_threshold: mean-reversion market — mean_reversion, funding_rate
    - BB width / ATR percentile: fine-grained volatility regime (optional)
    """

    def __init__(
        self,
        adx_period: int = 14,
        trending_threshold: float = 25.0,
        bb_period: int = 20,
        bb_std: float = 2.0,
        atr_lookback: int = 100,
    ) -> None:
        self._adx_period = adx_period
        self._trending_threshold = trending_threshold
        self._bb_period = bb_period
        self._bb_std = bb_std
        self._atr_lookback = atr_lookback

        # Incremental state for on_bar path
        self._max_bars = max(adx_period * 3, atr_lookback, bb_period) + 50
        self._highs: deque[float] = deque(maxlen=self._max_bars)
        self._lows: deque[float] = deque(maxlen=self._max_bars)
        self._closes: deque[float] = deque(maxlen=self._max_bars)

        # Cached regime
        self._last_regime: MarketRegime = MarketRegime()
        # Throttle the O(n) recompute so the per-bar hot path is amortized
        # rather than O(n^2) over a session. The regime is a slow-moving
        # classification; recomputing every bar is wasteful.
        self._recompute_every = max(1, adx_period // 2)
        self._bars_since_recompute = 0

    def update(self, high: float, low: float, close: float) -> MarketRegime:
        """Incremental regime update for on_bar path.

        Appends bar data and recomputes regime from the accumulated series
        on a throttled cadence (every ``_recompute_every`` bars) to keep the
        per-bar cost bounded instead of O(n^2) over the session.
        """
        self._highs.append(high)
        self._lows.append(low)
        self._closes.append(close)

        if len(self._closes) < self._adx_period * 2:
            return self._last_regime

        self._bars_since_recompute += 1
        if self._bars_since_recompute < self._recompute_every:
            return self._last_regime
        self._bars_since_recompute = 0

        h = pd.Series(self._highs)
        lows = pd.Series(self._lows)
        c = pd.Series(self._closes)

        adx_val = float(adx_vectorized(h, lows, c, period=self._adx_period).iloc[-1])
        # Guard NaN during warmup: NaN comparisons return False, which would
        # silently classify valid-but-partial warmup bars as mean_reversion.
        if math.isnan(adx_val):
            return self._last_regime

        # BB width as percentage of middle band
        bb_middle = c.rolling(self._bb_period).mean()
        bb_std_val = c.rolling(self._bb_period).std()
        bb_width = self._bb_std * 2 * bb_std_val
        if len(bb_middle) > 0 and not pd.isna(bb_middle.iloc[-1]):
            bb_width_pct = float(
                (bb_width / bb_middle.replace(0, 1e-10)).iloc[-1] * 100
            )
            if math.isnan(bb_width_pct):
                bb_width_pct = 0.0
        else:
            bb_width_pct = 0.0

        # ATR percentile
        tr = pd.concat(
            [
                h - lows,
                (h - c.shift(1)).abs(),
                (lows - c.shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(self._adx_period).mean()
        lookback = atr.tail(min(len(atr), self._atr_lookback))
        if len(lookback.dropna()) > 5:
            atr_percentile = float(
                (lookback.rank(pct=True)).iloc[-1]
            )
        else:
            atr_percentile = 0.5

        self._last_regime = MarketRegime(
            adx=adx_val,
            is_trending=adx_val >= self._trending_threshold,
            bb_width_pct=bb_width_pct,
            atr_percentile=atr_percentile,
        )
        return self._last_regime

    def detect(self, df: pd.DataFrame) -> MarketRegime:
        """Vectorized regime detection from OHLCV DataFrame.

        Parameters
        ----------
        df : pd.DataFrame
            Must have 'high', 'low', 'close' columns.

        Returns
        -------
        MarketRegime
            Latest regime classification.
        """
        if len(df) < self._adx_period * 2:
            return MarketRegime()

        adx_val = float(
            adx_vectorized(df["high"], df["low"], df["close"], period=self._adx_period).iloc[-1]
        )

        close = df["close"]
        bb_middle = close.rolling(self._bb_period).mean()
        bb_std_val = close.rolling(self._bb_period).std()
        bb_width = self._bb_std * 2 * bb_std_val
        bb_width_pct = float(
            (bb_width / bb_middle.replace(0, 1e-10)).iloc[-1] * 100
        ) if not bb_middle.iloc[-1:] .isna().all() else 0.0

        # ATR percentile
        hi, lo, c = df["high"], df["low"], df["close"]
        tr = pd.concat(
            [
                hi - lo,
                (hi - c.shift(1)).abs(),
                (lo - c.shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(self._adx_period).mean()
        lookback = atr.tail(min(len(atr), self._atr_lookback))
        if len(lookback.dropna()) > 5:
            atr_percentile = float((lookback.rank(pct=True)).iloc[-1])
        else:
            atr_percentile = 0.5

        self._last_regime = MarketRegime(
            adx=adx_val,
            is_trending=adx_val >= self._trending_threshold,
            bb_width_pct=bb_width_pct,
            atr_percentile=atr_percentile,
        )
        return self._last_regime
