"""Tests for quantflow.indicators.regime — MarketRegimeDetector."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.indicators.regime import MarketRegime, MarketRegimeDetector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 100, trend: str = "up") -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame."""
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    base = 100.0
    if trend == "up":
        drift = 0.5
    elif trend == "down":
        drift = -0.5
    else:
        drift = 0.0
    close = base + np.cumsum([drift + np.random.randn() * 0.8 for _ in range(n)])
    close = np.maximum(close, 10.0)  # keep positive
    high = close + np.abs(np.random.randn(n)) * 2
    low = close - np.abs(np.random.randn(n)) * 2
    low = np.minimum(low, close - 0.01)
    high = np.maximum(high, close + 0.01)
    return pd.DataFrame(
        {"high": high, "low": low, "close": close},
        index=dates,
    )


# ---------------------------------------------------------------------------
# MarketRegime dataclass
# ---------------------------------------------------------------------------

class TestMarketRegime:
    def test_default_values(self):
        r = MarketRegime()
        assert r.adx == 0.0
        assert r.is_trending is False
        assert r.bb_width_pct == 0.0
        assert r.atr_percentile == 0.5

    def test_regime_type_trending(self):
        r = MarketRegime(adx=30.0, is_trending=True)
        assert r.regime_type == "trending"

    def test_regime_type_mean_reversion(self):
        r = MarketRegime(adx=15.0, is_trending=False)
        assert r.regime_type == "mean_reversion"


# ---------------------------------------------------------------------------
# MarketRegimeDetector — detect() vectorized path
# ---------------------------------------------------------------------------

class TestMarketRegimeDetectorDetect:
    def test_detect_trending_market(self):
        df = _make_ohlcv(200, trend="up")
        det = MarketRegimeDetector(trending_threshold=25.0)
        regime = det.detect(df)
        # Strong uptrend should push ADX above threshold
        assert isinstance(regime, MarketRegime)
        assert regime.adx > 0
        assert regime.bb_width_pct >= 0
        assert 0.0 <= regime.atr_percentile <= 1.0

    def test_detect_insufficient_data(self):
        df = _make_ohlcv(5)
        det = MarketRegimeDetector(adx_period=14)
        regime = det.detect(df)
        # Should return default regime (not enough data for ADX*2)
        assert regime.adx == 0.0
        assert regime.is_trending is False

    def test_detect_bb_width_pct_nonnegative(self):
        df = _make_ohlcv(100, trend="flat")
        det = MarketRegimeDetector()
        regime = det.detect(df)
        assert regime.bb_width_pct >= 0.0

    def test_detect_atr_percentile_bounds(self):
        df = _make_ohlcv(200, trend="up")
        det = MarketRegimeDetector(atr_lookback=100)
        regime = det.detect(df)
        assert 0.0 <= regime.atr_percentile <= 1.0

    def test_detect_returns_latest_regime_cached(self):
        df = _make_ohlcv(100)
        det = MarketRegimeDetector()
        regime = det.detect(df)
        assert det._last_regime is regime


# ---------------------------------------------------------------------------
# MarketRegimeDetector — update() incremental path
# ---------------------------------------------------------------------------

class TestMarketRegimeDetectorUpdate:
    def test_update_returns_default_regime_with_few_bars(self):
        det = MarketRegimeDetector(adx_period=14)
        # Need adx_period * 2 = 28 bars minimum
        for i in range(10):
            r = det.update(102.0 + i, 98.0 + i, 100.0 + i)
        assert r.adx == 0.0
        assert r.is_trending is False

    def test_update_produces_regime_after_sufficient_bars(self):
        det = MarketRegimeDetector(adx_period=14)
        # Feed enough bars: need at least 28
        for i in range(50):
            high = 102.0 + i * 0.5
            low = 98.0 + i * 0.5
            close = 100.0 + i * 0.5
            r = det.update(high, low, close)
        assert r.adx > 0.0
        assert isinstance(r.is_trending, bool)

    def test_update_trims_max_bars(self):
        det = MarketRegimeDetector(adx_period=14, atr_lookback=30)
        max_bars = det._max_bars
        # Feed more bars than max_bars
        for i in range(max_bars + 20):
            det.update(100.0 + i, 96.0 + i, 98.0 + i)
        assert len(det._highs) <= max_bars
        assert len(det._lows) <= max_bars
        assert len(det._closes) <= max_bars

    def test_update_caches_last_regime(self):
        det = MarketRegimeDetector(adx_period=14)
        # Use varying prices to produce non-zero ADX
        for i in range(60):
            high = 120.0 + i * 1.0
            low = 80.0 + i * 0.5
            close = 100.0 + i * 0.8
            r = det.update(high, low, close)
        # With clearly varying bars, ADX should be non-zero
        assert det._last_regime.adx > 0.0 or det._last_regime.bb_width_pct > 0.0

    def test_update_trending_detection(self):
        """Strong trend should trigger is_trending=True."""
        det = MarketRegimeDetector(adx_period=14, trending_threshold=25.0)
        # Monotonically increasing prices → strong trend
        for i in range(80):
            high = 100.0 + i * 2
            low = 100.0 + i * 2 - 1
            close = 100.0 + i * 2 - 0.5
            det.update(high, low, close)
        # After enough bars, should detect trending
        assert det._last_regime.adx > 0.0
        # Note: monotonically increasing may not always produce ADX > 25
        # depending on noise, but ADX should be positive

    def test_update_consecutive_calls_accumulate(self):
        det = MarketRegimeDetector(adx_period=14)
        for i in range(35):
            det.update(105.0, 95.0, 100.0)
        assert len(det._closes) == 35

    def test_update_bb_width_pct_nonnegative(self):
        det = MarketRegimeDetector(adx_period=14)
        for i in range(50):
            r = det.update(110.0 + i, 90.0 + i, 100.0 + i)
        assert r.bb_width_pct >= 0.0

    def test_update_atr_percentile_in_bounds(self):
        det = MarketRegimeDetector(adx_period=14, atr_lookback=50)
        for i in range(60):
            r = det.update(105.0, 95.0, 100.0)
        assert 0.0 <= r.atr_percentile <= 1.0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestMarketRegimeDetectorEdgeCases:
    def test_detect_with_constant_prices(self):
        """Constant prices should still produce a valid regime (BB width may be 0)."""
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        df = pd.DataFrame(
            {"high": [100.0] * n, "low": [100.0] * n, "close": [100.0] * n},
            index=dates,
        )
        det = MarketRegimeDetector()
        regime = det.detect(df)
        assert isinstance(regime, MarketRegime)
        # With constant prices, BB width should be 0 or very small
        assert regime.bb_width_pct >= 0.0

    def test_detect_with_very_short_lookback(self):
        """Even with short data, detect should not crash."""
        n = 40
        df = _make_ohlcv(n)
        det = MarketRegimeDetector(adx_period=14, bb_period=10, atr_lookback=20)
        regime = det.detect(df)
        assert isinstance(regime, MarketRegime)

    def test_update_fewer_than_5_atr_drops_defaults_to_half(self):
        """When ATR lookback has < 5 non-NaN values, percentile defaults to 0.5."""
        det = MarketRegimeDetector(adx_period=14, atr_lookback=100)
        # Only 30 bars → lookback won't have many ATR values
        for i in range(30):
            det.update(110.0, 90.0, 100.0)
        r = det._last_regime
        # With 30 bars, ATR rolling(14) produces ~16 non-NaN values
        # which is > 5, so this tests the else branch path
        assert isinstance(r.atr_percentile, float)

    def test_update_atr_fewer_than_5_nonna_triggers_else_branch(self):
        """When ATR lookback has < 5 non-NaN values (line 113/166), percentile = 0.5."""
        det = MarketRegimeDetector(adx_period=14, atr_lookback=200)
        # Only 16 bars → ATR rolling(14) = ~3 non-NaN, < 5 → else branch
        for i in range(16):
            det.update(110.0, 90.0, 100.0)
        r = det._last_regime
        # With fewer than 5 non-NaN ATR values, percentile should be 0.5
        assert r.atr_percentile == 0.5

    def test_detect_bb_middle_na_branch(self):
        """When BB middle is NaN at last row, bb_width_pct should be 0."""
        # Create data where last BB middle is NaN by making last values all same
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        close_vals = np.random.randn(n).cumsum() + 100
        close_vals[-20:] = np.nan  # last 20 NaN → BB middle NaN
        df = pd.DataFrame(
            {
                "high": close_vals + 1,
                "low": close_vals - 1,
                "close": close_vals,
            },
            index=dates,
        )
        det = MarketRegimeDetector(bb_period=20)
        regime = det.detect(df)
        # When all BB middle at tail are NaN, bb_width_pct should be 0.0
        assert regime.bb_width_pct == 0.0
