"""Tests for honest n_trials accounting."""

from __future__ import annotations

import pytest

from quantflow.strategy.research.n_trials_budget import (
    TrialsBreakdown,
    account_n_trials,
    assert_honest_n_trials,
    grid_size,
)


def test_grid_and_account() -> None:
    # 3 * 4 * 3 = 36 style example from plan (use 3x4x2)
    space = {"a": (1, 2, 3), "b": (1, 2, 3, 4), "c": (1, 2)}
    assert grid_size(space) == 24
    bd = TrialsBreakdown(barrier_grid=24, optimize_trials=50, cpcv_paths=28, wfo_windows=5)
    acc = account_n_trials(bd)
    assert acc.n_trials_accounted == 24 + 50 + 28 + 5
    assert acc.underreported is False


def test_underreported() -> None:
    bd = TrialsBreakdown(barrier_grid=10, optimize_trials=5)
    acc = assert_honest_n_trials(3, bd)
    assert acc.underreported is True
    assert acc.n_trials_accounted == 15


def test_zero_budget_min_one() -> None:
    acc = account_n_trials(TrialsBreakdown())
    assert acc.n_trials_accounted == 1


def test_negative_raises() -> None:
    with pytest.raises(ValueError):
        account_n_trials({"barrier_grid": -1})
