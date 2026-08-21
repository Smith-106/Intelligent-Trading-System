"""Additional branch coverage for causal helpers, critical levels, and indicator engine."""

from __future__ import annotations

import ast
import inspect

import numpy as np
import pandas as pd
import pytest

from quantflow.indicators.causal import (
    assert_frame_causal,
    assert_series_causal,
    scan_callable_for_negative_shift,
    scan_source_for_negative_shift,
    shift_for_trade,
)
from quantflow.indicators.critical_level import (
    BreachDirection,
    CriticalLevel,
    CriticalLevelDetector,
    CriticalLevelType,
)
from quantflow.indicators.engine import IndicatorEngine
from quantflow.indicators.wave_models import WaveCount, WavePattern, WaveSegment
from quantflow.indicators.zigzag import PivotDirection, PivotPoint


def _pivot(index: int, price: float, direction: PivotDirection) -> PivotPoint:
    return PivotPoint(index=index, price=price, direction=direction, timestamp=index)


def _wave(label: int, start_price: float, end_price: float) -> WaveSegment:
    direction = PivotDirection.HIGH if end_price >= start_price else PivotDirection.LOW
    return WaveSegment(
        label=label,
        start=_pivot(
            0,
            start_price,
            PivotDirection.LOW if direction == PivotDirection.HIGH else PivotDirection.HIGH,
        ),
        end=_pivot(1, end_price, direction),
    )


def _ohlcv(n: int = 80, *, timestamp: bool = False) -> pd.DataFrame:
    close = pd.Series(np.linspace(100.0, 180.0, n), dtype=float)
    data: dict[str, object] = {
        "open": close,
        "high": close + 2.0,
        "low": close - 2.0,
        "close": close,
        "volume": np.linspace(100.0, 1000.0, n),
    }
    if timestamp:
        data["timestamp"] = pd.Series(np.arange(n), dtype=np.int64)
    return pd.DataFrame(data)


class TestCausalCoverage:
    def test_shift_zero_and_short_input(self) -> None:
        source = pd.Series([1, 2, 3], dtype=int)
        result = shift_for_trade(source, bars=0)
        assert result.dtype == float
        assert result.tolist() == [1.0, 2.0, 3.0]
        with pytest.raises(ValueError, match="at least"):
            assert_series_causal(lambda frame: frame["x"], pd.DataFrame({"x": range(10)}))

    def test_causal_boundary_guards(self) -> None:
        frame = pd.DataFrame({"x": np.arange(20, dtype=float)})

        # min_prefix=0 includes k=0, which is intentionally skipped.
        assert_series_causal(lambda value: value["x"], frame, min_prefix=0)

        # A short computed prefix exercises the warm-up guard without a failure.
        assert_series_causal(lambda value: value["x"].iloc[:1], frame, min_prefix=10)

    def test_causal_type_and_frame_checks(self) -> None:
        frame = pd.DataFrame({"x": np.arange(70, dtype=float), "y": np.arange(70, dtype=float)})
        with pytest.raises(TypeError, match="must return Series"):
            assert_series_causal(lambda _: pd.DataFrame(), frame, min_prefix=50)
        assert_frame_causal(lambda value: value, frame, ["x", "y"], min_prefix=50)

    def test_causal_nan_pattern_and_value_failures(self) -> None:
        frame = pd.DataFrame({"x": np.arange(70, dtype=float)})

        def nan_at_cut(value: pd.DataFrame) -> pd.Series:
            result = value["x"].copy()
            if len(value) < 70:
                result.iloc[0] = np.nan
            return result

        with pytest.raises(AssertionError, match="NaN-pattern"):
            assert_series_causal(nan_at_cut, frame, min_prefix=50)

        def future_dependent(value: pd.DataFrame) -> pd.Series:
            result = value["x"].copy()
            if len(value) < 70:
                result.iloc[0] = 999.0
            return result

        with pytest.raises(AssertionError, match="look-ahead"):
            assert_series_causal(future_dependent, frame, min_prefix=50)

    def test_negative_shift_ast_variants_and_invalid_source(self) -> None:
        source = """
        def f(s):
            a = s.shift(-1)
            b = s.shift(periods=-2)
            c = shift(-3)
            return a + b + c
        """
        findings = scan_source_for_negative_shift(source, where="variants")
        assert [finding.detail for finding in findings] == [
            "shift(-1) pulls future values (look-ahead)",
            "shift(-2) pulls future values (look-ahead)",
            "shift(-3) pulls future values (look-ahead)",
        ]
        assert scan_source_for_negative_shift("def broken(:") == []
        assert scan_source_for_negative_shift("s.shift(periods=n)") == []
        assert (
            scan_source_for_negative_shift("def f(s):\n    return s.shift(periods=n, foo=1)\n")
            == []
        )
        assert scan_source_for_negative_shift("def f(s):\n    return s.shift(-n)\n") == []

    def test_callable_source_fallback_and_clean_callable(self) -> None:
        def clean(value: pd.Series) -> pd.Series:
            return value.shift(1)

        assert scan_callable_for_negative_shift(clean) == []
        assert scan_callable_for_negative_shift(len) == []
        with pytest.raises(SyntaxError):
            ast.parse("def broken(:")
        assert inspect.isfunction(clean)


class TestCriticalLevelCoverage:
    def test_impulse_bearish_directions_and_missing_waves(self) -> None:
        count = WaveCount(
            pattern=WavePattern.IMPULSE,
            waves={
                1: _wave(1, 120.0, 100.0),
                3: _wave(3, 110.0, 90.0),
                4: _wave(4, 80.0, 100.0),
            },
        )
        levels = CriticalLevelDetector().detect(count).levels
        assert [level.level_type for level in levels] == [
            CriticalLevelType.W1_ORIGIN,
            CriticalLevelType.W1_PEAK,
            CriticalLevelType.W3_PEAK,
            CriticalLevelType.W4_LOW,
        ]
        assert [level.breach_direction for level in levels] == [
            BreachDirection.ABOVE,
            BreachDirection.BELOW,
            BreachDirection.BELOW,
            BreachDirection.BELOW,
        ]

        only_waves = CriticalLevelDetector().detect(
            WaveCount(pattern=WavePattern.IMPULSE, waves={2: _wave(2, 100.0, 110.0)})
        )
        assert only_waves.levels == []
        assert only_waves.active_bull_scenario is not None
        assert only_waves.active_bull_scenario.trigger_level is None
        assert only_waves.active_bull_scenario.targets == []
        assert only_waves.active_bear_scenario is not None
        assert only_waves.active_bear_scenario.trigger_level is None
        assert only_waves.active_bear_scenario.targets == []

    def test_compute_and_detect_empty_and_corrective_paths(self) -> None:
        detector = CriticalLevelDetector()

        missing = detector.compute(pd.DataFrame(index=[0, 1]))
        assert missing.isna().all()

        unknown = detector.detect(WaveCount())
        assert unknown.levels == []
        assert unknown.active_bull_scenario is None
        assert unknown.active_bear_scenario is None

        only_soft = WaveCount(
            pattern=WavePattern.CORRECTIVE,
            waves={-2: _wave(-2, 100.0, 115.0)},
        )
        no_hard = detector.compute(pd.DataFrame({"close": [110.0]}), wave_count=only_soft)
        assert no_hard.isna().all()

        corrective = detector.detect(
            WaveCount(
                pattern=WavePattern.CORRECTIVE,
                waves={
                    -1: _wave(-1, 120.0, 100.0),
                    -2: _wave(-2, 100.0, 115.0),
                },
            )
        )
        assert [level.level_type for level in corrective.levels] == [
            CriticalLevelType.W1_ORIGIN,
            CriticalLevelType.W1_PEAK,
        ]
        assert corrective.levels[0].severity == "hard"
        assert corrective.levels[1].severity == "soft"

    def test_scenario_false_branches_for_missing_wave_and_zero_amplitude(self) -> None:
        detector = CriticalLevelDetector()

        corrective_without_b = detector.detect(
            WaveCount(
                pattern=WavePattern.CORRECTIVE,
                waves={-1: _wave(-1, 100.0, 100.0)},
            )
        )
        assert len(corrective_without_b.levels) == 1
        assert corrective_without_b.levels[0].level_type == CriticalLevelType.W1_ORIGIN

        zero_impulse = detector.detect(
            WaveCount(
                pattern=WavePattern.IMPULSE,
                waves={1: _wave(1, 100.0, 100.0)},
            )
        )
        assert zero_impulse.active_bull_scenario is not None
        assert zero_impulse.active_bull_scenario.targets == []
        assert zero_impulse.active_bear_scenario is not None
        assert zero_impulse.active_bear_scenario.targets == []

        count = WaveCount(
            pattern=WavePattern.IMPULSE,
            waves={1: _wave(1, 100.0, 120.0), 3: _wave(3, 110.0, 150.0)},
        )
        frame = pd.DataFrame({"close": [130.0, 140.0]})
        result = detector.compute(frame, wave_count=count)
        assert result.eq(120.0).all()

        no_close = detector.compute(pd.DataFrame(index=[0, 1]), wave_count=count)
        assert no_close.eq(100.0).all()

    def test_bear_scenario_skips_non_origin_levels_before_trigger(self) -> None:
        detector = CriticalLevelDetector()
        levels = [
            CriticalLevel(110.0, CriticalLevelType.W1_PEAK, "peak", 1),
            CriticalLevel(100.0, CriticalLevelType.W1_ORIGIN, "origin", 1),
        ]
        scenario = detector._build_bear_scenario(WaveCount(pattern=WavePattern.UNKNOWN), levels)
        assert scenario.trigger_level == levels[1]


class TestIndicatorEngineCoverage:
    def test_batch_calculate_returns_copy_without_close(self) -> None:
        engine = IndicatorEngine()
        frame = pd.DataFrame({"open": [100.0], "high": [101.0]})

        result = engine.batch_calculate(frame)

        assert result.equals(frame)

    def test_batch_defaults_for_missing_ohlcv_columns(self) -> None:
        engine = IndicatorEngine()
        frame = pd.DataFrame({"close": np.linspace(100.0, 180.0, 80)})
        result = engine.batch_calculate(frame)
        assert len(result) == len(frame)
        assert {"sma_20", "session_vwap", "tsi"}.issubset(result.columns)

        engine = IndicatorEngine()
        requested = [
            "dema_20",
            "supertrend",
            "supertrend_direction",
            "stochrsi_k",
            "stochrsi_d",
            "kc_upper",
            "kc_middle",
            "kc_lower",
            "dc_upper",
            "dc_middle",
            "dc_lower",
            "session_vwap",
            "obv_slope",
            "cvd_proxy",
            "cci_20",
            "roc_12",
            "mom_10",
            "aroon_up",
            "aroon_down",
            "aroon_osc",
            "cmf_20",
            "realized_vol_20",
            "bb_width_20",
            "percent_b_20",
            "trix_15",
            "tsi",
        ]
        result = engine.compute_all(_ohlcv(timestamp=True), requested)
        assert set(requested).issubset(result.columns)
        assert "rsi_14" not in result.columns

    def test_compute_all_uses_default_high_low_volume_and_ignores_unknown(self) -> None:
        engine = IndicatorEngine()
        frame = pd.DataFrame({"close": np.linspace(100.0, 180.0, 80)})
        result = engine.compute_all(
            frame,
            ["stoch_k", "stoch_d", "vwap", "mfi_14", "volume_ratio", "aroon_up", "unknown"],
        )
        assert {"stoch_k", "stoch_d", "vwap", "mfi_14", "volume_ratio", "aroon_up"}.issubset(
            result.columns
        )
        assert "unknown" not in result.columns

    def test_compute_all_single_aroon_and_bollinger_members(self) -> None:
        engine = IndicatorEngine()
        result = engine.compute_all(
            _ohlcv(), ["bb_upper", "aroon_down", "kc_lower", "dc_middle", "supertrend_direction"]
        )
        assert {"bb_upper", "aroon_down", "kc_lower", "dc_middle", "supertrend_direction"}.issubset(
            result.columns
        )
