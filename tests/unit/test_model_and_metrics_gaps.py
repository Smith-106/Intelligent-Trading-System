"""Focused tests for remaining model, engine, portfolio, and metric gaps."""

from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from quantflow.common.models import Bar, Direction
from quantflow.indicators.critical_level import (
    BreachDirection,
    CriticalLevelDetector,
    CriticalLevels,
    CriticalLevelType,
)
from quantflow.indicators.engine import IndicatorEngine
from quantflow.indicators.wave_models import (
    AnalysisMode,
    IronLawResult,
    WaveCount,
    WavePattern,
    WaveSegment,
)
from quantflow.indicators.zigzag import PivotDirection, PivotPoint
from quantflow.signal.portfolio import PortfolioManager
from quantflow.signal.risk_metrics import calmar_ratio, conditional_var, sharpe_ratio, sortino_ratio
from quantflow.strategy.base import StrategyBase, StrategyContext
from quantflow.strategy.research.optimizer import StrategyOptimizer


def _pivot(index: int, price: float, direction: PivotDirection) -> PivotPoint:
    return PivotPoint(index=index, price=price, direction=direction, timestamp=index)


def _wave(label: int, start_idx: int, start_price: float, end_idx: int, end_price: float) -> WaveSegment:
    direction = PivotDirection.HIGH if end_price >= start_price else PivotDirection.LOW
    return WaveSegment(
        label=label,
        start=_pivot(
            start_idx,
            start_price,
            PivotDirection.LOW if direction == PivotDirection.HIGH else PivotDirection.HIGH,
        ),
        end=_pivot(end_idx, end_price, direction),
    )


class _Strategy(StrategyBase):
    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        return pd.Series(False, index=df.index), pd.Series(False, index=df.index)


def _ohlcv(length: int = 30) -> pd.DataFrame:
    close = pd.Series(np.linspace(100.0, 130.0, length), dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": pd.Series(np.linspace(1000.0, 2000.0, length), dtype=float),
        }
    )


class TestWaveModelsGaps:
    def test_wave_count_accessors_and_critical_levels(self) -> None:
        w1 = _wave(1, 0, 100.0, 2, 120.0)
        w3 = _wave(3, 3, 110.0, 5, 150.0)
        w4 = _wave(4, 5, 150.0, 6, 140.0)
        count = WaveCount(pattern=WavePattern.IMPULSE, waves={1: w1, 3: w3, 4: w4})

        assert count.get_wave(1) is w1
        assert count.get_wave(99) is None
        assert count.critical_levels() == {
            "w1_start": 100.0,
            "w1_end": 120.0,
            "w3_end": 150.0,
            "w4_end": 140.0,
        }

    def test_iron_law_result_validity_and_warning_flags(self) -> None:
        assert IronLawResult().is_valid is True
        assert IronLawResult(warnings=["soft"]).has_warnings is True
        assert IronLawResult(law1_ok=False).is_valid is False
        assert (
            IronLawResult(law2_ok=False, law2_mode=AnalysisMode.RETROSPECTIVE).is_valid is False
        )
        assert IronLawResult(law3_ok=False, law3_diagonal=True).is_valid is True
        assert IronLawResult(law3_ok=False, law3_diagonal=False).is_valid is False


class TestCriticalLevelDetectorGaps:
    def test_compute_handles_missing_wave_count_and_missing_hard_levels(self) -> None:
        detector = CriticalLevelDetector()
        df = _ohlcv(3)

        no_wave = detector.compute(df)
        no_hard = detector.compute(df, wave_count=WaveCount(pattern=WavePattern.UNKNOWN))

        assert no_wave.isna().all()
        assert no_hard.isna().all()

    def test_compute_uses_nearest_hard_level_and_detect_unknown_pattern(self) -> None:
        detector = CriticalLevelDetector()
        df = pd.DataFrame(index=pd.RangeIndex(4))
        wave_count = WaveCount(pattern=WavePattern.UNKNOWN)

        detected = detector.detect(wave_count)
        computed = detector.compute(
            df,
            wave_count=WaveCount(
                pattern=WavePattern.IMPULSE,
                waves={1: _wave(1, 0, 100.0, 1, 120.0)},
            ),
        )

        assert detected == CriticalLevels()
        assert computed.eq(100.0).all()

    def test_detect_builds_impulse_and_corrective_levels_and_targets(self) -> None:
        detector = CriticalLevelDetector()
        impulse = detector.detect(
            WaveCount(
                pattern=WavePattern.IMPULSE,
                waves={
                    1: _wave(1, 0, 100.0, 1, 120.0),
                    3: _wave(3, 2, 110.0, 3, 150.0),
                    4: _wave(4, 3, 150.0, 4, 140.0),
                },
            )
        )
        corrective = detector.detect(
            WaveCount(
                pattern=WavePattern.CORRECTIVE,
                waves={
                    -1: _wave(-1, 0, 120.0, 1, 100.0),
                    -2: _wave(-2, 1, 100.0, 2, 110.0),
                },
            )
        )

        assert [level.level_type for level in impulse.levels] == [
            CriticalLevelType.W1_ORIGIN,
            CriticalLevelType.W1_PEAK,
            CriticalLevelType.W3_PEAK,
            CriticalLevelType.W4_LOW,
        ]
        assert impulse.levels[0].breach_direction == BreachDirection.BELOW
        assert impulse.levels[1].breach_direction == BreachDirection.ABOVE
        assert impulse.active_bull_scenario is not None
        assert impulse.active_bull_scenario.targets == pytest.approx([132.36, 152.36], rel=1e-4)
        assert impulse.active_bear_scenario is not None
        assert impulse.active_bear_scenario.targets == pytest.approx([87.64, 80.0], rel=1e-4)
        assert [level.level_type for level in corrective.levels] == [
            CriticalLevelType.W1_ORIGIN,
            CriticalLevelType.W1_PEAK,
        ]
        assert corrective.active_bull_scenario is not None
        assert corrective.active_bull_scenario.trigger_level == corrective.levels[1]
        assert corrective.active_bear_scenario is not None
        assert corrective.active_bear_scenario.trigger_level == corrective.levels[0]


class TestStrategyBaseGaps:
    def test_strategy_context_properties_and_signal_clamping(self) -> None:
        ctx = StrategyContext()
        data = pd.DataFrame({"close": [1.0, 2.0]})
        params = {"alpha": 1}
        ctx.data = data
        ctx.params = params
        ctx.emit_signal("BTC/USDT", Direction.LONG, strength=2.0, price=101.0, strategy_id="s1")

        signals = ctx.flush_signals()

        assert ctx.data is data
        assert ctx.params == params
        assert len(signals) == 1
        assert signals[0].strength == 1.0
        assert ctx.flush_signals() == []

    def test_strategy_base_defaults_and_param_setter(self) -> None:
        strategy = _Strategy(params={"foo": "bar"})
        ctx = StrategyContext()
        bar = Bar(
            symbol="BTC/USDT",
            timestamp=1,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=10.0,
        )

        strategy.params = {"beta": 2}

        assert strategy.name == "_Strategy"
        assert strategy.params == {"beta": 2}
        strategy.on_init(ctx)
        strategy.on_bar(ctx, bar)
        strategy.on_tick(ctx, {"price": 100.5})
        assert strategy.get_required_indicators() == []


class TestIndicatorEngineGaps:
    def test_batch_calculate_returns_input_when_close_missing(self) -> None:
        engine = IndicatorEngine()
        df = pd.DataFrame({"open": [1.0, 2.0], "high": [2.0, 3.0]})

        result = engine.batch_calculate(df)

        assert result.equals(df)

    def test_compute_all_filters_to_requested_indicator_subset(self) -> None:
        engine = IndicatorEngine()
        df = _ohlcv(25)

        result = engine.compute_all(df, ["rsi_14", "atr_14"])

        assert "rsi_14" in result.columns
        assert "atr_14" in result.columns
        assert "sma_20" not in result.columns
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]


class TestPortfolioManagerGaps:
    def test_properties_zero_delta_position_scaling_and_snapshot(self) -> None:
        pm = PortfolioManager(100000.0)

        pm.update_position("BTC/USDT", 0.0, 50000.0)
        assert pm.positions == {}
        assert pm.cash == 100000.0
        assert pm.equity == 100000.0
        assert pm.get_position("BTC/USDT") is None
        assert pm.has_position("BTC/USDT") is False

        pm.update_position("BTC/USDT", 1.0, 50000.0)
        pm.update_position("BTC/USDT", 1.0, 52000.0)

        pos = pm.get_position("BTC/USDT")
        assert pos is not None
        assert pos.entry_price == pytest.approx(51000.0)
        assert pm.snapshot()["positions"] == 1

    def test_partial_close_short_position_and_allocation_lookup(self) -> None:
        pm = PortfolioManager(100000.0)
        pm.update_position("ETH/USDT", -2.0, 3000.0)
        pm.update_position("ETH/USDT", 1.0, 2800.0)
        pm.update_market_prices({"ETH/USDT": 2700.0})
        pm.mark_to_market({"ETH/USDT": 2600.0})
        pm.set_allocation({"mean_rev": 0.4})

        pos = pm.get_position("ETH/USDT")
        assert pos is not None
        assert pos.quantity == -1.0
        assert pm.cash == pytest.approx(100200.0)
        assert pos.unrealized_pnl == pytest.approx(400.0)
        assert pm.get_strategy_allocation("mean_rev") == 0.4
        assert pm.get_strategy_allocation("missing") == 0.0
        assert pm.allocation == {"mean_rev": 0.4}


class TestRiskMetricsGaps:
    def test_metric_short_circuit_paths(self) -> None:
        assert conditional_var(pd.Series([0.01, np.nan])) == 0.0
        assert sharpe_ratio(pd.Series([0.01])) == 0.0
        assert sortino_ratio(pd.Series([0.01, 0.02, 0.03])) == 0.0
        assert sortino_ratio(pd.Series([-0.01, -0.01, -0.01])) == 0.0
        assert calmar_ratio(pd.Series([0.01]), pd.Series([100.0])) == 0.0
        assert calmar_ratio(pd.Series([0.01, 0.02, 0.03]), pd.Series([100.0, 110.0, 120.0])) == 0.0

    def test_calmar_ratio_positive_when_drawdown_exists(self) -> None:
        returns = pd.Series([0.01, 0.015, -0.005, 0.02], dtype=float)
        equity = pd.Series([100.0, 105.0, 95.0, 110.0], dtype=float)

        result = calmar_ratio(returns, equity, periods_per_year=12)

        assert result > 0


class TestOptimizerGaps:
    def test_optimize_downgrades_non_finite_objectives(self) -> None:
        class _Engine:
            def run_backtest(
                self,
                close: pd.Series,
                entries: pd.Series,
                exits: pd.Series,
                initial_capital: float,
                fee: float,
            ) -> object:
                class _Result:
                    sharpe_ratio = float("nan")
                    sortino_ratio = float("nan")
                    calmar_ratio = float("nan")
                    total_return = float("nan")

                return _Result()

        close = pd.Series([100.0, 101.0, 102.0, 103.0], dtype=float)

        def _signal_fn(
            close_series: pd.Series,
            **params: float,
        ) -> tuple[pd.Series, pd.Series]:
            del params
            empty = pd.Series(False, index=close_series.index)
            return empty, empty

        optimizer = StrategyOptimizer(engine=cast(Any, _Engine()))
        result = optimizer.optimize(
            close=close,
            signal_fn=_signal_fn,
            param_space={"threshold": (0.0, 0.1)},
            n_trials=2,
            objective="sharpe",
        )

        assert result["best_value"] == -10.0
        assert "threshold" in result["best_params"]
