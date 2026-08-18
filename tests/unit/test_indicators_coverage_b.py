from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from quantflow.indicators.divergence import DivergenceDetector
from quantflow.indicators.elliott_wave import (
    WaveLabel,
    WaveType,
    classify_corrective,
    classify_impulse,
    elliott_wave,
    wave_momentum_divergence,
    zigzag,
)
from quantflow.indicators.regime import MarketRegime, MarketRegimeDetector
from quantflow.indicators.wave_identifier import WaveIdentifier
from quantflow.indicators.wave_models import (
    AnalysisMode,
    IronLawResult,
    WaveCount,
    WavePattern,
    WaveSegment,
)
from quantflow.indicators.zigzag import (
    PivotDirection,
    PivotPoint,
    PivotSequence,
    ZigZagIndicator,
    _merge_pivot_runs,
    _zigzag_single,
)


def pivot(index: int, price: float, direction: PivotDirection) -> PivotPoint:
    return PivotPoint(index=index, price=price, direction=direction, timestamp=index * 100)


def wave(label: int, start: tuple[int, float], end: tuple[int, float]) -> WaveSegment:
    direction = PivotDirection.HIGH if end[1] >= start[1] else PivotDirection.LOW
    return WaveSegment(
        label=label,
        start=pivot(start[0], start[1], PivotDirection.LOW if direction == PivotDirection.HIGH else PivotDirection.HIGH),
        end=pivot(end[0], end[1], direction),
    )


def ohlc(n: int = 40) -> pd.DataFrame:
    close = pd.Series(np.linspace(100.0, 140.0, n))
    return pd.DataFrame({"high": close + 1, "low": close - 1, "close": close})


class TestWaveModelsCoverage:
    def test_segments_count_levels_and_laws(self) -> None:
        seg = wave(1, (0, 100.0), (2, 120.0))
        assert seg.price_range() == (100.0, 120.0)
        assert seg.amplitude() == 20.0
        count = WaveCount(
            pattern=WavePattern.IMPULSE,
            current_wave=3,
            waves={1: seg, 3: wave(3, (2, 110.0), (4, 140.0)), 4: wave(4, (4, 140.0), (5, 130.0))},
            mode=AnalysisMode.RETROSPECTIVE,
            confidence=0.8,
        )
        assert count.get_wave(1) is seg
        assert count.get_wave(9) is None
        assert count.critical_levels() == {"w1_start": 100.0, "w1_end": 120.0, "w3_end": 140.0, "w4_end": 130.0}
        assert IronLawResult().is_valid is True
        assert IronLawResult(law1_ok=False).is_valid is False
        assert IronLawResult(law2_mode=AnalysisMode.RETROSPECTIVE, law2_ok=False).is_valid is False
        assert IronLawResult(law3_ok=False, law3_diagonal=True).is_valid is True
        assert IronLawResult(warnings=["x"]).has_warnings is True
        assert WaveCount().critical_levels() == {}
        assert PivotSequence().confirmed_pivots() == []
        assert len(PivotSequence([pivot(0, 1, PivotDirection.LOW)]).confirmed_pivots()) == 1


class TestRegimeCoverage:
    def test_update_throttle_and_nan_guards(self, monkeypatch: pytest.MonkeyPatch) -> None:
        det = MarketRegimeDetector(adx_period=2, bb_period=3, atr_lookback=20)
        monkeypatch.setattr(
            "quantflow.indicators.regime.adx_vectorized",
            lambda h, l, c, period: pd.Series([np.nan] * len(h), index=h.index),
        )
        for i in range(4):
            result = det.update(101 + i, 99 + i, 100 + i)
        assert result.adx == 0.0
        assert det._bars_since_recompute == 0
        # A second detector exercises the throttled return before recomputation.
        det2 = MarketRegimeDetector(adx_period=4)
        for i in range(8):
            first = det2.update(101 + i, 99 + i, 100 + i)
        before = det2._bars_since_recompute
        assert det2.update(110, 90, 105) is det2._last_regime
        assert det2._bars_since_recompute == 0
        assert before == 1

    def test_update_bb_nan_and_atr_default_branches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        det = MarketRegimeDetector(adx_period=2, bb_period=20, atr_lookback=100)
        monkeypatch.setattr(
            "quantflow.indicators.regime.adx_vectorized",
            lambda h, l, c, period: pd.Series([30.0] * len(h), index=h.index),
        )
        for _ in range(4):
            result = det.update(101.0, 99.0, 100.0)
        assert result.is_trending is True
        assert result.bb_width_pct == 0.0
        assert result.atr_percentile == 0.5

    def test_detect_nan_adx_and_zero_middle_width(self, monkeypatch: pytest.MonkeyPatch) -> None:
        det = MarketRegimeDetector(adx_period=2, bb_period=3, atr_lookback=10)
        df = pd.DataFrame({"high": [1.0] * 5, "low": [1.0] * 5, "close": [0.0] * 5})
        monkeypatch.setattr(
            "quantflow.indicators.regime.adx_vectorized",
            lambda h, l, c, period: pd.Series([np.nan] * len(h), index=h.index),
        )
        # detect has no NaN guard by design, but still exercises its BB/ATR branches.
        result = det.detect(df)
        assert np.isnan(result.adx)
        assert result.bb_width_pct == 0.0
        assert result.atr_percentile == 0.5


class TestDivergenceCoverage:
    def test_compute_and_detect_missing_columns_and_bearish_volume(self) -> None:
        detector = DivergenceDetector()
        df = pd.DataFrame(index=range(5))
        count = WaveCount(pattern=WavePattern.IMPULSE, waves={3: wave(3, (0, 100), (1, 130)), 5: wave(5, (2, 120), (3, 140))})
        assert detector.compute(df, wave_count=count).eq(0).all()
        result = detector.detect(count, df)
        assert result.divergences == []
        volume = pd.DataFrame({"volume": [100.0, 100.0, 1000.0, 50.0, 1.0]})
        vol = detector._check_volume_divergence(count.waves, volume)
        assert vol is not None and vol.divergence_type == "volume_bearish"

    def test_detect_handles_helpers_without_divergence(self) -> None:
        detector = DivergenceDetector()
        count = WaveCount(
            pattern=WavePattern.IMPULSE,
            waves={
                2: wave(2, (0, 100), (1, 90)),
                3: wave(3, (0, 100), (1, 130)),
                5: wave(5, (2, 120), (3, 140)),
            },
        )
        frame = pd.DataFrame(
            {
                "macd_histogram": [0.0, 0.0],
                "volume": [1.0, 1.0],
                "rsi_14": [40.0, 50.0],
            }
        )
        with patch.object(detector, "_check_macd_divergence", return_value=None), patch.object(
            detector, "_check_volume_divergence", return_value=None
        ), patch.object(detector, "_check_rsi_divergence", return_value=None):
            result = detector.detect(count, frame)
        assert result.divergences == []
        assert result.bearish is False
        assert result.bullish is False

        count = WaveCount(
            pattern=WavePattern.IMPULSE,
            waves={
                2: wave(2, (0, 100), (1, 90)),
                3: wave(3, (0, 100), (1, 130)),
                5: wave(5, (2, 120), (3, 140)),
            },
        )
        with patch.object(
            detector,
            "_check_macd_divergence",
            return_value=SimpleNamespace(divergence_type="macd_other"),
        ), patch.object(
            detector,
            "_check_volume_divergence",
            return_value=SimpleNamespace(divergence_type="volume_other"),
        ), patch.object(
            detector,
            "_check_rsi_divergence",
            return_value=SimpleNamespace(divergence_type="rsi_other"),
        ):
            result = detector.detect(
                count,
                pd.DataFrame(
                    {
                        "macd_histogram": [0.0, 0.0],
                        "volume": [1.0, 1.0],
                        "rsi_14": [40.0, 50.0],
                    }
                ),
            )
        assert result.bearish is False
        assert result.bullish is False
        assert len(result.divergences) == 3


    def test_divergence_edge_guards_and_rsi_zero_amplitude(self) -> None:
        detector = DivergenceDetector()
        data = pd.DataFrame({"macd_histogram": [1.0] * 3, "volume": [1.0] * 3, "rsi_14": [40.0] * 3})
        w3 = wave(3, (0, 100), (1, 90))
        assert detector._check_macd_divergence({3: w3, 5: wave(5, (1, 90), (2, 80))}, data) is None
        assert detector._check_volume_divergence({3: w3, 5: wave(5, (1, 90), (2, 80))}, data) is None
        assert detector._check_rsi_divergence({1: wave(1, (0, 100), (1, 100)), 2: wave(2, (1, 100), (2, 90))}, data) is None
        assert detector._check_rsi_divergence({1: wave(1, (0, 100), (1, 110)), 2: wave(2, (1, 110), (2, 104))}, data) is None

    def test_bearish_rsi_is_not_a_bullish_signal(self) -> None:
        detector = DivergenceDetector()
        data = pd.DataFrame({"rsi_14": [40.0, 50.0, 60.0]})
        result = detector._check_rsi_divergence(
            {1: wave(1, (0, 110), (1, 100)), 2: wave(2, (1, 100), (2, 90))}, data
        )
        assert result is None


class TestLegacyElliottCoverage:
    def test_zigzag_initial_updates_and_direction_extensions(self) -> None:
        high = pd.Series([100, 101, 103, 102, 104, 95, 94, 100, 101], dtype=float)
        low = pd.Series([99, 98, 97, 96, 98, 90, 89, 92, 95], dtype=float)
        result = zigzag(high, low, threshold=0.03)
        assert not result.empty
        assert set(result.columns) == {"pivot_idx", "pivot_price", "pivot_type"}
        # Exercise the same transition logic in the legacy helper.
        assert not _zigzag_single(high, low, threshold=0.03).empty
        # Both initial direction branches and final-pivot behavior are covered by these swings.
        assert set(result["pivot_type"]).issubset({-1, 1})

    def test_classifiers_valid_and_all_rejection_conditions(self) -> None:
        bullish = pd.DataFrame({"pivot_idx": range(5), "pivot_price": [100, 120, 110, 155, 115], "pivot_type": [-1, 1, -1, 1, -1]})
        assert classify_impulse(bullish) is not None
        zero_w1 = bullish.copy(); zero_w1.loc[:, "pivot_price"] = [100, 100, 95, 130, 120]
        bad_r2 = bullish.copy(); bad_r2.loc[2, "pivot_price"] = 119
        bad_r3 = bullish.copy(); bad_r3.loc[3, "pivot_price"] = 105
        overlap = bullish.copy(); overlap.loc[4, "pivot_price"] = 125
        assert classify_impulse(zero_w1) is None
        assert classify_impulse(bad_r2) is None
        assert classify_impulse(bad_r3) is None
        assert classify_impulse(overlap) is None
        corrective = pd.DataFrame({"pivot_idx": [0, 1, 2], "pivot_price": [100, 115, 108], "pivot_type": [-1, 1, -1]})
        assert classify_corrective(corrective) is not None

    def test_elliott_empty_and_mapping_skips_unknown_index(self, monkeypatch: pytest.MonkeyPatch) -> None:
        df = pd.DataFrame({"high": [100, 101], "low": [99, 100]}, index=[10, 20])
        empty = pd.DataFrame(columns=["pivot_idx", "pivot_price", "pivot_type"])
        monkeypatch.setattr("quantflow.indicators.elliott_wave.zigzag", lambda *a, **k: empty)
        assert (elliott_wave(df)["wave_label"] == 0).all()
        pivots = pd.DataFrame([{"pivot_idx": 0, "pivot_price": 99.0, "pivot_type": -1}])
        monkeypatch.setattr("quantflow.indicators.elliott_wave.zigzag", lambda *a, **k: pivots)
        monkeypatch.setattr("quantflow.indicators.elliott_wave.classify_impulse", lambda *a, **k: None)
        monkeypatch.setattr("quantflow.indicators.elliott_wave.classify_corrective", lambda *a, **k: None)
        assert (elliott_wave(df)["wave_label"] == 0).all()

    def test_elliott_mapping_skips_index_after_dataframe_index_changes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        frame = pd.DataFrame(
            {"high": [101.0, 102.0, 103.0], "low": [99.0, 100.0, 101.0]},
            index=[0, 1, 2],
        )
        pivots = pd.DataFrame(
            [{"pivot_idx": 0, "pivot_price": 100.0, "pivot_type": -1}]
        )
        mapped = pd.DataFrame(
            {
                "pivot_idx": [0],
                "pivot_price": [100.0],
                "wave_label": [WaveLabel.WA],
                "wave_type": [WaveType.CORRECTIVE],
                "is_bullish": [True],
            }
        )

        def mutate_index(*args: object, **kwargs: object) -> pd.DataFrame:
            frame.index = [10, 11, 12]
            return pivots

        monkeypatch.setattr("quantflow.indicators.elliott_wave.zigzag", mutate_index)
        monkeypatch.setattr(
            "quantflow.indicators.elliott_wave.classify_impulse",
            lambda *args, **kwargs: mapped,
        )
        result = elliott_wave(frame)
        assert result["wave_label"].eq(0).all()

    def test_momentum_divergence_low_high_and_bounds(self) -> None:
        close = pd.Series([100, 95, 90, 80, 130, 130], dtype=float)
        rsi = pd.Series([50, 40, 55, 60, 30, 40], dtype=float)
        pivots = pd.DataFrame({"pivot_idx": [1, 2, 3, 4], "pivot_type": [-1, 1, -1, 1]})
        result = wave_momentum_divergence(close, rsi, pivots, lookback=1)
        assert result.iloc[3] == 1
        assert result.iloc[4] == -1
        assert result.iloc[5] == 0
        out = pivots.copy(); out.loc[4, "pivot_idx"] = 99
        assert wave_momentum_divergence(close, rsi, out, lookback=1).iloc[0] == 0

        non_wave_pivot = pd.DataFrame(
            {"pivot_idx": [1, 2, 3, 4], "pivot_type": [-1, 1, -1, 0]}
        )
        result = wave_momentum_divergence(close, rsi, non_wave_pivot, lookback=1)
        assert result.iloc[4] == 0




class TestWaveIdentifierCoverage:
    def test_compute_and_corrective_and_bearish_impulse(self) -> None:
        identifier = WaveIdentifier()
        df = pd.DataFrame(index=range(4))
        assert identifier.compute(df).eq(0).all()
        points = [pivot(0, 130, PivotDirection.HIGH), pivot(1, 100, PivotDirection.LOW), pivot(2, 118, PivotDirection.HIGH), pivot(3, 70, PivotDirection.LOW), pivot(4, 125, PivotDirection.HIGH)]
        result = identifier._try_impulse(points, AnalysisMode.RETROSPECTIVE)
        assert result is not None and result.pattern == WavePattern.IMPULSE
        points = [pivot(0, 120, PivotDirection.HIGH), pivot(1, 100, PivotDirection.LOW), pivot(2, 110, PivotDirection.HIGH), pivot(3, 90, PivotDirection.LOW)]
        correction = identifier._try_corrective(points, AnalysisMode.PROGRESSIVE)
        assert correction is not None and correction.pattern == WavePattern.CORRECTIVE

    def test_iron_laws_valid_and_bearish_diagonal_paths(self) -> None:
        identifier = WaveIdentifier()
        valid = {1: wave(1, (0, 100), (1, 130)), 2: wave(2, (1, 130), (2, 120)), 3: wave(3, (2, 120), (3, 170)), 4: wave(4, (3, 170), (4, 150)), 5: wave(5, (4, 150), (5, 180))}
        result = identifier._validate_iron_laws(valid, AnalysisMode.RETROSPECTIVE, True)
        assert result.is_valid is True and result.law2_ok is True and result.violations == []
        identified = identifier.identify(PivotSequence([pivot(0, 100, PivotDirection.LOW), pivot(1, 130, PivotDirection.HIGH), pivot(2, 120, PivotDirection.LOW), pivot(3, 170, PivotDirection.HIGH), pivot(4, 150, PivotDirection.LOW)]), AnalysisMode.PROGRESSIVE)
        assert identified.pattern == WavePattern.IMPULSE
        bearish = {1: wave(1, (0, 120), (1, 100)), 2: wave(2, (1, 100), (2, 110)), 3: wave(3, (2, 110), (3, 80)), 4: wave(4, (3, 80), (4, 90)), 5: wave(5, (4, 90), (5, 70))}
        checked_bearish = identifier._validate_iron_laws(bearish, AnalysisMode.PROGRESSIVE, False)
        assert checked_bearish.law3_ok is True
        no_overlap = {1: wave(1, (0, 100), (1, 120)), 4: wave(4, (3, 140), (4, 130))}
        assert identifier._validate_iron_laws(no_overlap, AnalysisMode.PROGRESSIVE, True).law3_ok is True

    def test_partial_impulse_and_diagonal_false(self) -> None:
        identifier = WaveIdentifier()
        points = [pivot(0, 100, PivotDirection.LOW), pivot(1, 120, PivotDirection.HIGH), pivot(2, 110, PivotDirection.LOW), pivot(3, 150, PivotDirection.HIGH), pivot(4, 130, PivotDirection.LOW)]
        partial = identifier._try_impulse(points, AnalysisMode.PROGRESSIVE)
        assert partial is not None and partial.current_wave == 4
        zero_retrace = [pivot(0, 100, PivotDirection.LOW), pivot(1, 120, PivotDirection.HIGH), pivot(2, 120, PivotDirection.LOW), pivot(3, 150, PivotDirection.HIGH), pivot(4, 140, PivotDirection.LOW)]
        assert identifier._try_impulse(zero_retrace, AnalysisMode.PROGRESSIVE) is not None
        assert identifier._check_diagonal({1: wave(1, (0, 100), (1, 120)), 2: wave(2, (1, 120), (2, 110)), 3: wave(3, (2, 110), (3, 140)), 4: wave(4, (3, 140), (4, 100)), 5: wave(5, (4, 100), (5, 150))}, True) is False


class TestZigzagCoverage:
    def test_sequence_helpers_and_compute(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seq = PivotSequence([pivot(0, 100, PivotDirection.LOW), pivot(2, 120, PivotDirection.HIGH)], overlap_ratio=0.8, thresholds_used=[0.05], degraded=True, consensus_n=1)
        assert len(seq.confirmed_pivots()) == 1
        copied = seq.with_confirmed_only()
        assert copied.degraded is True and copied.thresholds_used == [0.05]
        indicator = ZigZagIndicator()
        monkeypatch.setattr(indicator, "compute_pivot_sequence", lambda *a, **k: seq)
        markers = indicator.compute(pd.DataFrame({"high": [100, 120, 110], "low": [99, 110, 100], "timestamp": [1, 2, 3]}))
        assert markers.iloc[0] == -1 and markers.iloc[2] == 1

    def test_compute_out_of_range_marker_and_merge_consensus(self, monkeypatch: pytest.MonkeyPatch) -> None:
        indicator = ZigZagIndicator()
        seq = PivotSequence([pivot(99, 1, PivotDirection.HIGH)])
        monkeypatch.setattr(indicator, "compute_pivot_sequence", lambda *a, **k: seq)
        result = indicator.compute(pd.DataFrame({"high": [1, 2, 3], "low": [0, 1, 2]}))
        assert result.eq(0).all()
        runs = [
            pd.DataFrame([{"pivot_idx": 1, "pivot_price": 100.0, "pivot_type": 1}]),
            pd.DataFrame([{"pivot_idx": 2, "pivot_price": 102.0, "pivot_type": 1}]),
        ]
        merged = _merge_pivot_runs(runs, min_overlap=2, bar_tolerance=2)
        assert len(merged) == 1 and merged.iloc[0]["overlap_count"] == 2

def test_divergence_zero_amplitude_guard_is_handled() -> None:
    class InconsistentPrice:
        def __gt__(self, other: object) -> bool:
            return True

        def __sub__(self, other: object) -> float:
            return 0.0

    detector = DivergenceDetector()
    w1 = WaveSegment(
        label=1,
        start=pivot(0, InconsistentPrice(), PivotDirection.LOW),  # type: ignore[arg-type]
        end=pivot(1, InconsistentPrice(), PivotDirection.HIGH),  # type: ignore[arg-type]
    )
    result = detector._check_rsi_divergence(
        {
            1: w1,
            2: wave(2, (1, 110.0), (2, 104.0)),
        },
        pd.DataFrame({"rsi_14": [40.0, 50.0, 60.0]}),
    )
    assert result is None


def test_legacy_elliott_direction_stability_and_corrective_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    up = zigzag(
        pd.Series([100.0, 111.0, 110.0]),
        pd.Series([99.0, 110.0, 109.0]),
        threshold=0.05,
    )
    down = zigzag(
        pd.Series([100.0, 90.0, 90.0]),
        pd.Series([99.0, 89.0, 90.0]),
        threshold=0.05,
    )
    assert up.iloc[-1]["pivot_type"] == 1
    assert down.iloc[-1]["pivot_type"] == -1

    pivots = pd.DataFrame(
        [
            {"pivot_idx": 0, "pivot_price": 100.0, "pivot_type": -1},
            {"pivot_idx": 1, "pivot_price": 115.0, "pivot_type": 1},
            {"pivot_idx": 2, "pivot_price": 108.0, "pivot_type": -1},
        ]
    )
    corrective = pd.DataFrame(
        {
            "pivot_idx": [0, 1, 2],
            "pivot_price": [100.0, 115.0, 108.0],
            "wave_label": [WaveLabel.WA, WaveLabel.WB, WaveLabel.WC],
            "wave_type": [WaveType.CORRECTIVE] * 3,
            "is_bullish": [True] * 3,
        }
    )
    monkeypatch.setattr(
        "quantflow.indicators.elliott_wave.zigzag",
        lambda *args, **kwargs: pivots,
    )
    monkeypatch.setattr(
        "quantflow.indicators.elliott_wave.classify_impulse",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "quantflow.indicators.elliott_wave.classify_corrective",
        lambda *args, **kwargs: corrective,
    )
    result = elliott_wave(
        pd.DataFrame(
            {
                "high": [101.0, 116.0, 109.0],
                "low": [99.0, 114.0, 107.0],
            }
        )
    )
    assert (result["wave_type"] == int(WaveType.CORRECTIVE)).sum() == 3


def test_legacy_momentum_divergence_negative_conditions() -> None:
    close = pd.Series([100.0, 100.0, 105.0, 105.0, 105.0])
    rsi = pd.Series([50.0] * 5)
    pivots = pd.DataFrame(
        {
            "pivot_idx": [1, 2, 3, 4],
            "pivot_type": [-1, 1, -1, 1],
        }
    )
    result = wave_momentum_divergence(close, rsi, pivots, lookback=1)
    assert result.eq(0).all()


def test_regime_update_handles_nan_bollinger_width(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = MarketRegimeDetector(adx_period=2, bb_period=1, atr_lookback=10)
    monkeypatch.setattr(
        "quantflow.indicators.regime.adx_vectorized",
        lambda high, low, close, period: pd.Series([30.0] * len(high), index=high.index),
    )
    for _ in range(4):
        regime = detector.update(101.0, 99.0, 100.0)
    assert regime.is_trending is True
    assert regime.bb_width_pct == 0.0


def test_wave_identifier_zero_amplitude_and_bearish_diagonal_paths() -> None:
    identifier = WaveIdentifier()
    zero_impulse = identifier._try_impulse(
        [
            pivot(0, 100.0, PivotDirection.HIGH),
            pivot(1, 100.0, PivotDirection.LOW),
            pivot(2, 110.0, PivotDirection.HIGH),
            pivot(3, 90.0, PivotDirection.LOW),
            pivot(4, 120.0, PivotDirection.HIGH),
        ],
        AnalysisMode.PROGRESSIVE,
    )
    assert zero_impulse is not None
    assert zero_impulse.waves[2].retracement_pct is None

    zero_corrective = identifier._try_corrective(
        [
            pivot(0, 100.0, PivotDirection.HIGH),
            pivot(1, 100.0, PivotDirection.LOW),
            pivot(2, 110.0, PivotDirection.HIGH),
            pivot(3, 90.0, PivotDirection.LOW),
        ],
        AnalysisMode.PROGRESSIVE,
    )
    assert zero_corrective is not None
    assert zero_corrective.waves[-2].retracement_pct is None

    law2 = identifier._validate_iron_laws(
        {
            1: wave(1, (0, 100.0), (1, 120.0)),
            3: wave(3, (2, 120.0), (3, 150.0)),
            5: wave(5, (4, 150.0), (5, 150.0)),
        },
        AnalysisMode.PROGRESSIVE,
        True,
    )
    assert law2.law2_ok is True

    bearish_diagonal = identifier._validate_iron_laws(
        {
            1: wave(1, (0, 120.0), (1, 80.0)),
            2: wave(2, (1, 80.0), (2, 110.0)),
            3: wave(3, (2, 110.0), (3, 90.0)),
            4: wave(4, (3, 90.0), (4, 100.0)),
            5: wave(5, (4, 100.0), (5, 95.0)),
        },
        AnalysisMode.PROGRESSIVE,
        False,
    )
    assert bearish_diagonal.law3_diagonal is True
    assert bearish_diagonal.warnings

    sparse_labels = {
        1: wave(1, (0, 100.0), (1, 120.0)),
        2: wave(2, (1, 120.0), (2, 110.0)),
        6: wave(6, (2, 110.0), (3, 111.0)),
        7: wave(7, (3, 111.0), (4, 112.0)),
        8: wave(8, (4, 112.0), (5, 113.0)),
    }
    assert identifier._check_diagonal(sparse_labels, True) is False


def test_zigzag_stable_direction_branches() -> None:
    up = _zigzag_single(
        pd.Series([100.0, 110.0, 109.0]),
        pd.Series([99.0, 108.0, 107.0]),
        threshold=0.05,
    )
    down = _zigzag_single(
        pd.Series([100.0, 90.0, 90.0]),
        pd.Series([99.0, 89.0, 90.0]),
        threshold=0.05,
    )
    assert up.iloc[-1]["pivot_type"] == 1
    assert down.iloc[-1]["pivot_type"] == -1


    upward_reversal = _zigzag_single(
        pd.Series([100.0, 110.0, 100.0]),
        pd.Series([99.0, 108.0, 95.0]),
        threshold=0.05,
    )
    downward_reversal = _zigzag_single(
        pd.Series([100.0, 90.0, 95.0]),
        pd.Series([99.0, 89.0, 90.0]),
        threshold=0.05,
    )
    assert upward_reversal.iloc[-1]["pivot_type"] == -1
    assert downward_reversal.iloc[-1]["pivot_type"] == 1

