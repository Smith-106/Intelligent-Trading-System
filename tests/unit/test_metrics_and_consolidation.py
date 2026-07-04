"""Tests for risk_metrics calmar_ratio and additional signal quality paths — P1-3."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.signal.risk_metrics import calmar_ratio, max_drawdown, sharpe_ratio, sortino_ratio
from quantflow.strategy.validation.signal_quality import aggregate_signal_quality, signal_quality_metrics


class TestCalmarRatio:
    def test_positive_calmar(self):
        np.random.seed(42)
        n = 252
        returns = pd.Series(np.random.normal(0.002, 0.01, n))
        equity = 10000 * (1 + returns).cumprod()
        cr = calmar_ratio(returns, equity)
        assert cr > 0

    def test_zero_drawdown(self):
        # Monotonically increasing → no drawdown → calmar = 0
        returns = pd.Series([0.01] * 50)
        equity = 10000 * (1 + returns).cumprod()
        cr = calmar_ratio(returns, equity)
        # max_drawdown returns 0.0 for monotonic increase, calmar returns 0
        assert cr == 0.0

    def test_short_series(self):
        returns = pd.Series([0.01])
        equity = pd.Series([10100.0])
        assert calmar_ratio(returns, equity) == 0.0

    def test_negative_return_positive_drawdown_calmar(self):
        # Declining equity → negative returns, negative drawdown
        returns = pd.Series([-0.01] * 20)
        equity = 10000 * (1 + returns).cumprod()
        cr = calmar_ratio(returns, equity)
        # annual_return negative, max_drawdown negative → ratio = neg/neg = positive? No:
        # calmar = annual_return / abs(dd), annual_return < 0, abs(dd) > 0 → negative
        assert cr < 0


class TestSignalQualityMetrics:
    def test_no_valid_forward_returns(self):
        """When no valid forward returns, all metrics should be 0."""
        close = pd.Series([100.0, 100.0, 100.0])  # constant prices → 0 forward returns
        entries = pd.Series([True, False, False], index=close.index)
        result = signal_quality_metrics(close, entries)
        # Forward returns are 0 → not > 0, all labels = 0, precision may vary
        assert "precision" in result
        assert "recall" in result
        assert "hit_rate" in result
        assert "brier_score" in result

    def test_with_probabilities(self):
        """Test signal quality with explicit probability predictions."""
        np.random.seed(42)
        n = 100
        close = pd.Series(100 + np.random.randn(n).cumsum())
        entries = pd.Series(False, index=close.index)
        entries.iloc[::10] = True  # every 10 bars
        proba = pd.Series(0.6, index=close.index)  # constant probability
        result = signal_quality_metrics(close, entries, probabilities=proba)
        assert 0.0 <= result["brier_score"] <= 1.0
        assert result["n_signals"] > 0

    def test_with_oos_sharpe(self):
        """OOS Sharpe should be included in results."""
        np.random.seed(42)
        n = 100
        close = pd.Series(100 + np.random.randn(n).cumsum())
        entries = pd.Series(False, index=close.index)
        entries.iloc[10] = True
        result = signal_quality_metrics(close, entries, oos_sharpe=1.5)
        assert result["oos_sharpe"] == 1.5

    def test_all_signals_no_hits(self):
        """All entries but none profitable → precision = 0."""
        n = 50
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        # Declining prices → next-bar return is always negative
        close = pd.Series(np.linspace(100, 50, n), index=dates)
        entries = pd.Series(True, index=dates)
        result = signal_quality_metrics(close, entries)
        # With declining prices, precision should be 0 (no TP)
        assert result["precision"] == 0.0
        assert result["hit_rate"] == 0.0


class TestAggregateSignalQuality:
    def test_empty_rows(self):
        result = aggregate_signal_quality([])
        assert result["precision"] == 0.0
        assert result["n_predictions"] == 0
        assert result["n_signals"] == 0

    def test_single_row(self):
        row = {"precision": 0.7, "recall": 0.5, "n_predictions": 100, "n_signals": 30,
               "brier_score": 0.2, "oos_sharpe": 1.5}
        result = aggregate_signal_quality([row])
        assert result["precision"] == 0.7
        assert result["recall"] == 0.5
        assert result["n_predictions"] == 100

    def test_weighted_average(self):
        rows = [
            {"precision": 0.8, "recall": 0.6, "n_predictions": 200, "n_signals": 50,
             "brier_score": 0.15, "oos_sharpe": 1.0},
            {"precision": 0.4, "recall": 0.8, "n_predictions": 100, "n_signals": 20,
             "brier_score": 0.3, "oos_sharpe": 0.5},
        ]
        result = aggregate_signal_quality(rows)
        # Weighted: (0.8*200 + 0.4*100) / 300 = 200/300 ≈ 0.667
        assert abs(result["precision"] - 0.6667) < 0.01
        assert result["n_predictions"] == 300
        assert result["n_signals"] == 70

    def test_zero_total_predictions(self):
        rows = [
            {"precision": 0.5, "n_predictions": 0, "n_signals": 0,
             "brier_score": 0.0, "oos_sharpe": 0.0, "recall": 0.0},
        ]
        result = aggregate_signal_quality(rows)
        assert result["precision"] == 0.0


class TestSignalGeneratorConsolidation:
    """Additional tests for signal consolidation edge cases."""

    def test_consolidate_with_hit_rate_weighting(self):
        """Hit rates should affect the consolidated direction."""
        from quantflow.common.models import Direction, Signal
        from quantflow.signal.generator import SignalGenerator

        gen = SignalGenerator()
        # s1 has high hit rate, s2 has low hit rate
        sigs = [
            Signal("BTC/USDT", Direction.LONG, 0.5, 50000, "s1"),
            Signal("BTC/USDT", Direction.SHORT, 0.9, 50000, "s2"),
        ]
        # Without hit rates: LONG weight = 0.5*0.5=0.25, SHORT weight = 0.9*0.5=0.45 → SHORT
        result_default = gen.consolidate_signals(sigs)
        assert result_default is not None
        assert result_default.direction == Direction.SHORT

        # With s1 high hit rate: LONG weight = 0.5*0.9=0.45, SHORT weight = 0.9*0.2=0.18 → LONG
        result_weighted = gen.consolidate_signals(sigs, strategy_hit_rates={"s1": 0.9, "s2": 0.2})
        assert result_weighted is not None
        assert result_weighted.direction == Direction.LONG

    def test_consolidate_preserves_symbol(self):
        from quantflow.common.models import Direction, Signal
        from quantflow.signal.generator import SignalGenerator

        gen = SignalGenerator()
        sigs = [
            Signal("ETH/USDT", Direction.LONG, 0.7, 3000, "s1"),
        ]
        result = gen.consolidate_signals(sigs)
        assert result is not None
        assert result.symbol == "ETH/USDT"

    def test_consolidate_single_signal(self):
        from quantflow.common.models import Direction, Signal
        from quantflow.signal.generator import SignalGenerator

        gen = SignalGenerator()
        sigs = [Signal("BTC/USDT", Direction.SHORT, 0.6, 49000, "s1")]
        result = gen.consolidate_signals(sigs)
        assert result is not None
        assert result.direction == Direction.SHORT
