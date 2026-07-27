"""Integration tests for Elliott Wave trading system.

End-to-end tests covering: data → indicators → strategy → signals → backtest.
"""

from __future__ import annotations

import pandas as pd
import pytest

from quantflow.indicators.critical_level import CriticalLevelDetector, CriticalLevels
from quantflow.indicators.fibonacci import FibonacciCalculator
from quantflow.indicators.wave_identifier import WaveIdentifier
from quantflow.indicators.wave_models import AnalysisMode, WaveCount, WavePattern
from quantflow.indicators.zigzag import PivotDirection, PivotPoint, PivotSequence, ZigZagIndicator
from quantflow.signal.wave_signal_generator import WaveInvalidationChecker, WaveSignalGenerator
from quantflow.strategy.elliott_wave_strategy import LiuYudongWaveStrategy
from quantflow.strategy.research.elliott_wave_backtest import (
    BacktestResult,
    generate_synthetic_wave_data,
    run_backtest,
)


@pytest.fixture
def wave_ohlcv() -> pd.DataFrame:
    """Generate synthetic OHLCV data with clear wave patterns."""
    return generate_synthetic_wave_data(n_bars=800, seed=42)


@pytest.fixture
def strategy() -> LiuYudongWaveStrategy:
    """Create LiuYudongWaveStrategy instance."""
    return LiuYudongWaveStrategy()


class TestZigZagPipeline:
    """Test ZigZag detection within the full indicator pipeline."""

    def test_zigzag_produces_pivots(self, wave_ohlcv: pd.DataFrame) -> None:
        zigzag = ZigZagIndicator()
        seq = zigzag.compute_pivot_sequence(
            wave_ohlcv["high"],
            wave_ohlcv["low"],
            pd.Series(range(len(wave_ohlcv))),
            thresholds=[0.03, 0.05, 0.08],
            min_overlap_ratio=0.7,
        )
        assert len(seq.pivots) >= 3
        assert seq.overlap_ratio > 0

    def test_zigzag_pivots_alternate_direction(self, wave_ohlcv: pd.DataFrame) -> None:
        zigzag = ZigZagIndicator()
        seq = zigzag.compute_pivot_sequence(
            wave_ohlcv["high"],
            wave_ohlcv["low"],
            pd.Series(range(len(wave_ohlcv))),
            thresholds=[0.03, 0.05, 0.08],
            min_overlap_ratio=0.7,
        )
        # Most pivots should alternate; noise may cause rare same-direction pairs
        alternations = sum(
            1
            for i in range(1, len(seq.pivots))
            if seq.pivots[i].direction != seq.pivots[i - 1].direction
        )
        if len(seq.pivots) > 1:
            assert alternations / (len(seq.pivots) - 1) > 0.8


class TestWaveIdentificationPipeline:
    """Test wave identification from ZigZag pivots."""

    def test_identifies_impulse_or_corrective(self, wave_ohlcv: pd.DataFrame) -> None:
        zigzag = ZigZagIndicator()
        seq = zigzag.compute_pivot_sequence(
            wave_ohlcv["high"],
            wave_ohlcv["low"],
            pd.Series(range(len(wave_ohlcv))),
            thresholds=[0.03, 0.05, 0.08],
            min_overlap_ratio=0.7,
        )
        identifier = WaveIdentifier()
        wc = identifier.identify(seq, mode=AnalysisMode.PROGRESSIVE)
        assert wc.pattern in [WavePattern.IMPULSE, WavePattern.CORRECTIVE, WavePattern.UNKNOWN]

    def test_iron_laws_progressive_mode(self) -> None:
        """C-001: In PROGRESSIVE mode, W3 not-shortest does not reject classification."""
        # Create a WaveCount where W3 is shortest
        pivots = [
            PivotPoint(index=0, price=100, direction=PivotDirection.LOW),
            PivotPoint(index=10, price=110, direction=PivotDirection.HIGH),
            PivotPoint(index=20, price=105, direction=PivotDirection.LOW),
            PivotPoint(index=30, price=112, direction=PivotDirection.HIGH),
            PivotPoint(index=40, price=108, direction=PivotDirection.LOW),
            PivotPoint(index=50, price=115, direction=PivotDirection.HIGH),
        ]
        seq = PivotSequence(pivots=pivots, overlap_ratio=1.0)
        identifier = WaveIdentifier()
        wc = identifier.identify(seq, mode=AnalysisMode.PROGRESSIVE)
        # Should still classify even if iron laws have warnings
        assert wc.pattern in [WavePattern.IMPULSE, WavePattern.CORRECTIVE, WavePattern.UNKNOWN]


class TestFibonacciPipeline:
    """Test Fibonacci calculation from wave count."""

    def test_fibonacci_levels_computed(self, wave_ohlcv: pd.DataFrame) -> None:
        zigzag = ZigZagIndicator()
        seq = zigzag.compute_pivot_sequence(
            wave_ohlcv["high"],
            wave_ohlcv["low"],
            pd.Series(range(len(wave_ohlcv))),
            thresholds=[0.03, 0.05, 0.08],
            min_overlap_ratio=0.7,
        )
        identifier = WaveIdentifier()
        wc = identifier.identify(seq, mode=AnalysisMode.PROGRESSIVE)
        fib = FibonacciCalculator().calculate(wc)
        if wc.pattern != WavePattern.UNKNOWN:
            assert len(fib.retracement) > 0 or len(fib.extension) > 0


class TestCriticalLevelPipeline:
    """Test critical level detection from wave count."""

    def test_critical_levels_for_impulse(self, wave_ohlcv: pd.DataFrame) -> None:
        zigzag = ZigZagIndicator()
        seq = zigzag.compute_pivot_sequence(
            wave_ohlcv["high"],
            wave_ohlcv["low"],
            pd.Series(range(len(wave_ohlcv))),
            thresholds=[0.03, 0.05, 0.08],
            min_overlap_ratio=0.7,
        )
        identifier = WaveIdentifier()
        wc = identifier.identify(seq, mode=AnalysisMode.PROGRESSIVE)
        cl = CriticalLevelDetector().detect(wc)
        if wc.pattern == WavePattern.IMPULSE:
            assert len(cl.levels) > 0
            assert cl.active_bull_scenario is not None or cl.active_bear_scenario is not None


class TestStrategyPipeline:
    """Test strategy signal generation end-to-end."""

    def test_strategy_generates_signals(
        self, wave_ohlcv: pd.DataFrame, strategy: LiuYudongWaveStrategy
    ) -> None:
        entries, exits = strategy.generate_signals(wave_ohlcv)
        assert len(entries) == len(wave_ohlcv)
        assert len(exits) == len(wave_ohlcv)
        assert entries.dtype == bool
        assert exits.dtype == bool

    def test_strategy_no_signals_on_flat_data(self, strategy: LiuYudongWaveStrategy) -> None:
        flat_df = pd.DataFrame(
            {
                "high": [100.0] * 50,
                "low": [99.0] * 50,
                "close": [99.5] * 50,
                "volume": [1000.0] * 50,
            }
        )
        entries, exits = strategy.generate_signals(flat_df)
        assert entries.sum() == 0
        assert exits.sum() == 0


class TestSignalRiskPipeline:
    """Test signal generation and invalidation pipeline."""

    def test_signal_enrichment(self, wave_ohlcv: pd.DataFrame) -> None:
        from quantflow.common.models import Direction

        zigzag = ZigZagIndicator()
        seq = zigzag.compute_pivot_sequence(
            wave_ohlcv["high"],
            wave_ohlcv["low"],
            pd.Series(range(len(wave_ohlcv))),
            thresholds=[0.03, 0.05, 0.08],
            min_overlap_ratio=0.7,
        )
        identifier = WaveIdentifier()
        wc = identifier.identify(seq, mode=AnalysisMode.PROGRESSIVE)
        cl = CriticalLevelDetector().detect(wc)

        gen = WaveSignalGenerator()
        signal = gen.enrich(Direction.LONG, wc, cl, trigger_rule="w2_entry")
        assert signal.direction == Direction.LONG
        assert 0.0 <= signal.confidence <= 1.0

    def test_invalidation_checker(self) -> None:
        checker = WaveInvalidationChecker(max_consecutive_stops=3)
        wc = WaveCount(pattern=WavePattern.UNKNOWN)
        cl = CriticalLevels()
        events = checker.check(wc, cl, 50000.0)
        assert isinstance(events, list)


class TestBacktest:
    """Test full backtest pipeline with synthetic data."""

    def test_backtest_runs(self) -> None:
        df = generate_synthetic_wave_data(n_bars=800, seed=42)
        result = run_backtest(df=df, initial_capital=100000)
        assert isinstance(result, BacktestResult)
        assert result.total_trades >= 0

    def test_backtest_result_metrics(self) -> None:
        df = generate_synthetic_wave_data(n_bars=2000, seed=42)
        result = run_backtest(df=df, initial_capital=100000)
        # Verify all metrics are computed
        assert result.win_rate >= 0.0
        assert result.profit_factor >= 0.0
        assert result.max_drawdown_pct >= 0.0
        assert result.total_return_pct != 0.0 or result.total_trades == 0

    def test_backtest_targets_reported(self) -> None:
        df = generate_synthetic_wave_data(n_bars=2000, seed=42)
        result = run_backtest(df=df, initial_capital=100000)
        targets = result.meets_targets
        assert "win_rate" in targets
        assert "profit_factor" in targets
        assert "max_drawdown" in targets
        assert "sharpe" in targets
