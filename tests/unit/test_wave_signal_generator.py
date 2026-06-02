"""Tests for wave signal generation and invalidation handling."""

from __future__ import annotations

from quantflow.common.models import Direction
from quantflow.indicators.critical_level import (
    BreachDirection,
    CriticalLevel,
    CriticalLevels,
    CriticalLevelType,
)
from quantflow.indicators.wave_models import WaveCount, WavePattern
from quantflow.signal.wave_signal_generator import (
    InvalidationSeverity,
    WaveInvalidationChecker,
    WaveSignalGenerator,
)


def _level(
    price: float,
    *,
    level_type: CriticalLevelType,
    breach_direction: BreachDirection,
    severity: str,
    description: str = "lvl",
) -> CriticalLevel:
    return CriticalLevel(
        price=price,
        level_type=level_type,
        description=description,
        wave_ref=1,
        breach_direction=breach_direction,
        severity=severity,
    )


class TestWaveSignalGenerator:
    def test_enrich_preserves_wave_metadata_and_hard_invalidations(self) -> None:
        generator = WaveSignalGenerator()
        wave_count = WaveCount(pattern=WavePattern.IMPULSE, current_wave=3, confidence=0.82)
        critical_levels = CriticalLevels(
            levels=[
                _level(
                    95.0,
                    level_type=CriticalLevelType.W1_ORIGIN,
                    breach_direction=BreachDirection.BELOW,
                    severity="hard",
                ),
                _level(
                    105.0,
                    level_type=CriticalLevelType.W3_PEAK,
                    breach_direction=BreachDirection.ABOVE,
                    severity="soft",
                ),
            ]
        )

        signal = generator.enrich(
            Direction.LONG,
            wave_count,
            critical_levels,
            trigger_rule="w2_entry",
            price=100.0,
        )

        assert signal.direction == Direction.LONG
        assert signal.price == 100.0
        assert signal.wave_label == 3
        assert signal.confidence == 0.82
        assert signal.trigger_rule == "w2_entry"
        assert len(signal.invalidation_points) == 1
        assert signal.invalidation_points[0].price == 95.0

    def test_compute_hard_and_soft_stops_for_long_and_short(self) -> None:
        generator = WaveSignalGenerator()
        critical_levels = CriticalLevels(
            levels=[
                _level(
                    94.0,
                    level_type=CriticalLevelType.W1_ORIGIN,
                    breach_direction=BreachDirection.BELOW,
                    severity="hard",
                ),
                _level(
                    92.0,
                    level_type=CriticalLevelType.W4_LOW,
                    breach_direction=BreachDirection.BELOW,
                    severity="hard",
                ),
                _level(
                    108.0,
                    level_type=CriticalLevelType.W3_PEAK,
                    breach_direction=BreachDirection.ABOVE,
                    severity="hard",
                ),
                _level(
                    97.0,
                    level_type=CriticalLevelType.FIB_TARGET,
                    breach_direction=BreachDirection.BELOW,
                    severity="soft",
                ),
                _level(
                    111.0,
                    level_type=CriticalLevelType.FIB_TARGET,
                    breach_direction=BreachDirection.ABOVE,
                    severity="soft",
                ),
            ]
        )

        assert generator._compute_hard_stop(Direction.LONG, critical_levels) == 92.0
        assert generator._compute_hard_stop(Direction.SHORT, critical_levels) == 108.0
        assert generator._compute_soft_stop(Direction.LONG, critical_levels) == 97.0
        assert generator._compute_soft_stop(Direction.SHORT, critical_levels) == 111.0

    def test_compute_stop_returns_none_when_matching_levels_missing(self) -> None:
        generator = WaveSignalGenerator()
        empty = CriticalLevels(levels=[])
        above_only = CriticalLevels(
            levels=[
                _level(
                    110.0,
                    level_type=CriticalLevelType.W3_PEAK,
                    breach_direction=BreachDirection.ABOVE,
                    severity="hard",
                )
            ]
        )

        assert generator._compute_hard_stop(Direction.LONG, empty) is None
        assert generator._compute_hard_stop(Direction.LONG, above_only) is None
        assert generator._compute_soft_stop(Direction.SHORT, empty) is None


class TestWaveInvalidationChecker:
    def test_check_emits_soft_and_hard_breach_events(self) -> None:
        checker = WaveInvalidationChecker(max_consecutive_stops=3)
        wave_count = WaveCount(pattern=WavePattern.IMPULSE, current_wave=4, confidence=0.7)
        critical_levels = CriticalLevels(
            levels=[
                _level(
                    95.0,
                    level_type=CriticalLevelType.W1_ORIGIN,
                    breach_direction=BreachDirection.BELOW,
                    severity="hard",
                    description="hard floor",
                ),
                _level(
                    105.0,
                    level_type=CriticalLevelType.W3_PEAK,
                    breach_direction=BreachDirection.ABOVE,
                    severity="soft",
                    description="soft ceiling",
                ),
            ]
        )

        events = checker.check(wave_count, critical_levels, current_price=106.0)

        assert len(events) == 1
        assert events[0].severity == InvalidationSeverity.SOFT
        assert "above critical 105.00" in events[0].description

        events = checker.check(wave_count, critical_levels, current_price=94.0)
        assert len(events) == 1
        assert events[0].severity == InvalidationSeverity.HARD
        assert "below critical 95.00" in events[0].description

    def test_check_adds_system_pause_after_consecutive_hard_stops(self) -> None:
        checker = WaveInvalidationChecker(max_consecutive_stops=2)
        wave_count = WaveCount(pattern=WavePattern.IMPULSE, current_wave=1, confidence=0.6)
        critical_levels = CriticalLevels(
            levels=[
                _level(
                    99.0,
                    level_type=CriticalLevelType.W1_ORIGIN,
                    breach_direction=BreachDirection.BELOW,
                    severity="hard",
                    description="origin",
                )
            ]
        )

        first = checker.check(wave_count, critical_levels, current_price=98.0)
        second = checker.check(wave_count, critical_levels, current_price=97.0)

        assert len(first) == 1
        assert len(second) == 2
        assert second[-1].critical_level.level_type == CriticalLevelType.SYSTEM_PAUSE
        assert second[-1].severity == InvalidationSeverity.HARD
        assert "2 consecutive hard stops" in second[-1].description

    def test_check_resets_consecutive_counter_when_no_hard_event_and_manual_reset(self) -> None:
        checker = WaveInvalidationChecker(max_consecutive_stops=2)
        wave_count = WaveCount(pattern=WavePattern.IMPULSE, current_wave=2, confidence=0.5)
        hard_levels = CriticalLevels(
            levels=[
                _level(
                    99.0,
                    level_type=CriticalLevelType.W1_ORIGIN,
                    breach_direction=BreachDirection.BELOW,
                    severity="hard",
                )
            ]
        )
        no_breach_levels = CriticalLevels(
            levels=[
                _level(
                    120.0,
                    level_type=CriticalLevelType.W3_PEAK,
                    breach_direction=BreachDirection.ABOVE,
                    severity="soft",
                )
            ]
        )

        checker.check(wave_count, hard_levels, current_price=98.0)
        assert checker.check(wave_count, no_breach_levels, current_price=100.0) == []

        checker.check(wave_count, hard_levels, current_price=98.0)
        checker.reset_consecutive()
        events = checker.check(wave_count, hard_levels, current_price=98.0)

        assert len(events) == 1
