"""Tests for triple-barrier labeling helpers."""

from __future__ import annotations

import pandas as pd
import pytest

from quantflow.strategy.validation.barriers import (
    minimum_track_record_length,
    triple_barrier_labels,
)


def test_triple_barrier_labels_cover_profit_stop_and_time() -> None:
    close = pd.Series(
        [100.0, 103.0, 97.0, 100.0, 100.5],
        index=pd.date_range("2024-01-01", periods=5, freq="D"),
    )

    labels = triple_barrier_labels(close, profit_take_pct=0.02, stop_loss_pct=0.02, max_holding=2)

    assert list(labels["label"]) == [1, -1, 1, 0, 0]
    assert list(labels["barrier_hit"]) == ["profit", "stop", "profit", "time", "time"]
    assert list(labels["holding_period"]) == [1, 1, 1, 2, 1]


def test_minimum_track_record_length_rejects_non_positive_sharpe() -> None:
    result = minimum_track_record_length(0.0)

    assert result == {"min_trl": float("inf"), "passed": False, "reason": "non_positive_sharpe"}


def test_minimum_track_record_length_returns_adjusted_metrics() -> None:
    result = minimum_track_record_length(1.5, skew=0.2, kurtosis=4.0, confidence=0.95)

    assert result["min_trl"] > 0
    assert result["sharpe"] == 1.5
    assert result["confidence"] == 0.95
    assert result["adjusted_factor"] == pytest.approx(2.3875)
