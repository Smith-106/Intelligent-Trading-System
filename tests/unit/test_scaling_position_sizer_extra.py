"""Additional branch coverage for progressive scaling position sizing."""

from __future__ import annotations

import pytest

from quantflow.execution.scaling_position_sizer import (
    PositionPhase,
    PositionRequest,
    ScalingConfig,
    ScalingPositionSizer,
)
from quantflow.indicators.wave_models import WaveCount, WavePattern


def _wave_count(current_wave: int) -> WaveCount:
    return WaveCount(pattern=WavePattern.IMPULSE, current_wave=current_wave)


class TestScalingPositionSizerExtra:
    def test_position_request_risk_reward_ratio_handles_none_zero_and_valid_case(self) -> None:
        assert (
            PositionRequest(
                phase=PositionPhase.TRIAL,
                size_pct=0.1,
                entry_price=100.0,
                stop_price=95.0,
                target_price=None,
            ).risk_reward_ratio
            is None
        )
        assert (
            PositionRequest(
                phase=PositionPhase.TRIAL,
                size_pct=0.1,
                entry_price=100.0,
                stop_price=100.0,
                target_price=110.0,
            ).risk_reward_ratio
            is None
        )
        assert PositionRequest(
            phase=PositionPhase.TRIAL,
            size_pct=0.1,
            entry_price=100.0,
            stop_price=95.0,
            target_price=115.0,
        ).risk_reward_ratio == pytest.approx(3.0)

    def test_trial_add_and_chase_return_zero_when_risk_per_unit_non_positive(self) -> None:
        sizer = ScalingPositionSizer()
        wave_count = _wave_count(2)

        trial = sizer.compute_trial_position(100000.0, 100.0, 100.0, wave_count.current_wave)
        add = sizer.compute_add_position(100000.0, 100.0, 100.0, wave_count.current_wave)
        chase = sizer.compute_chase_position(100000.0, 100.0, 100.0, wave_count.current_wave)

        assert trial.phase == PositionPhase.TRIAL
        assert add.phase == PositionPhase.ADD
        assert chase.phase == PositionPhase.CHASE
        assert trial.size_pct == 0
        assert add.size_pct == 0
        assert chase.size_pct == 0
        assert trial.risk_pct == 0
        assert add.risk_pct == 0
        assert chase.risk_pct == 0

    def test_trial_add_and_chase_are_capped_by_config_and_remaining_capacity(self) -> None:
        config = ScalingConfig(trial_pct=0.10, add_pct=0.20, chase_pct=0.15, max_position_pct=0.30)
        sizer = ScalingPositionSizer(config)
        wave_count = _wave_count(3)

        trial = sizer.compute_trial_position(100000.0, 100.0, 99.0, wave_count.current_wave)
        assert trial.size_pct == pytest.approx(0.10)
        assert trial.risk_pct == pytest.approx(0.001)

        sizer._current_position_pct = 0.25
        add = sizer.compute_add_position(100000.0, 100.0, 99.0, wave_count.current_wave)
        chase = sizer.compute_chase_position(100000.0, 100.0, 99.0, wave_count.current_wave)

        assert add.size_pct == pytest.approx(0.05)
        assert chase.size_pct == pytest.approx(0.05)
        assert add.risk_pct == pytest.approx(0.0005)
        assert chase.risk_pct == pytest.approx(0.0005)
        assert add.wave_label == 3
        assert chase.wave_label == 3

    def test_compute_add_and_chase_can_hit_zero_when_no_remaining_capacity(self) -> None:
        sizer = ScalingPositionSizer(ScalingConfig(max_position_pct=0.4))
        sizer._current_position_pct = 0.4
        wave_count = _wave_count(5)

        add = sizer.compute_add_position(100000.0, 100.0, 99.0, wave_count.current_wave)
        chase = sizer.compute_chase_position(100000.0, 100.0, 99.0, wave_count.current_wave)

        assert add.size_pct == 0.0
        assert chase.size_pct == 0.0

    def test_exit_schedule_and_trailing_stop_follow_config(self) -> None:
        config = ScalingConfig(exit_first_pct=0.25, exit_second_pct=0.35, exit_final_pct=0.40)
        sizer = ScalingPositionSizer(config)

        exits = sizer.compute_exit_schedule(100.0, 120.0, 130.0)
        stop = sizer.update_trailing_stop(current_price=125.0, wave_low=108.0, cost_basis=110.0)

        assert [exit_req.phase for exit_req in exits] == [
            PositionPhase.EXIT_FIRST,
            PositionPhase.EXIT_SECOND,
            PositionPhase.EXIT_FINAL,
        ]
        assert [exit_req.size_pct for exit_req in exits] == [0.25, 0.35, 0.40]
        assert exits[0].target_price == 120.0
        assert exits[1].target_price == 130.0
        assert exits[2].target_price is None
        assert stop == 110.0

    def test_check_risk_limits_and_size_adapter(self) -> None:
        sizer = ScalingPositionSizer(
            ScalingConfig(trial_pct=0.12, daily_loss_limit_pct=0.05, monthly_loss_limit_pct=0.10)
        )

        limits = sizer.check_risk_limits(100000.0, daily_pnl=-5000.0, monthly_pnl=-10000.0)
        sized = sizer.size(100000.0, 100.0, 99.0)

        assert limits == {"daily_loss": False, "monthly_loss": False}
        assert sized == pytest.approx(0.12)
