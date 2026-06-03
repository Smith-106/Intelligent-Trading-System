"""Additional coverage for data cleaner edge cases."""

from __future__ import annotations

import pandas as pd
import pytest

from quantflow.data.cleaner import (
    _detect_outliers,
    _validate_no_future_leak,
    clean_ohlcv,
    validate_no_future_leak,
)


def test_clean_ohlcv_converts_datetime_column_and_interpolates_prices() -> None:
    df = pd.DataFrame(
        {
            "datetime": ["2024-01-02T00:00:00Z", "2024-01-01T00:00:00Z", "2024-01-03T00:00:00Z"],
            "open": [100.0, None, 104.0],
            "high": [101.0, None, 105.0],
            "low": [99.0, None, 103.0],
            "close": [100.5, None, 104.5],
            "volume": [10.0, None, 30.0],
        }
    )

    cleaned = clean_ohlcv(
        df,
        remove_outliers=False,
        fill_method="interpolate",
        validate_no_future_leak=False,
    )

    assert pd.api.types.is_datetime64_any_dtype(cleaned["datetime"])
    assert cleaned["datetime"].is_monotonic_increasing
    assert pd.isna(cleaned["open"].iloc[0])
    assert cleaned["open"].iloc[1] == 100.0
    assert cleaned["volume"].iloc[0] == 0


def test_clean_ohlcv_forward_fills_missing_prices() -> None:
    df = pd.DataFrame(
        {
            "timestamp": [1, 2, 3],
            "open": [100.0, None, 104.0],
            "high": [101.0, None, 105.0],
            "low": [99.0, None, 103.0],
            "close": [100.5, None, 104.5],
        }
    )

    cleaned = clean_ohlcv(
        df, remove_outliers=False, fill_method="ffill", validate_no_future_leak=False
    )

    assert cleaned.loc[1, "open"] == 100.0
    assert cleaned.loc[1, "high"] == 101.0
    assert cleaned.loc[1, "low"] == 99.0
    assert cleaned.loc[1, "close"] == 100.5


def test_validate_no_future_leak_uses_datetime_and_ignores_missing_columns() -> None:
    safe = pd.DataFrame({"value": [1, 2, 3]})
    future_dt = pd.DataFrame(
        {"datetime": pd.to_datetime(["2035-01-01T00:00:00Z", "2035-01-02T00:00:00Z"], utc=True)}
    )

    assert validate_no_future_leak(safe, cutoff_timestamp=0) is True
    assert validate_no_future_leak(future_dt, cutoff_timestamp=1_700_000_000_000) is False


def test_validate_no_future_leak_defaults_cutoff_when_not_provided() -> None:
    recent = pd.DataFrame({"timestamp": [1_700_000_000_000]})

    assert validate_no_future_leak(recent) is True


def test_internal_validate_no_future_leak_handles_missing_and_nondatetime_columns() -> None:
    _validate_no_future_leak(pd.DataFrame({"close": [1.0]}), "timestamp")
    _validate_no_future_leak(pd.DataFrame({"timestamp": [1, 2, 3]}), "timestamp")


def test_internal_validate_no_future_leak_raises_for_future_datetime() -> None:
    df = pd.DataFrame({"timestamp": pd.to_datetime(["2999-01-01T00:00:00Z"], utc=True)})

    with pytest.raises(ValueError, match="Future data detected"):
        _validate_no_future_leak(df, "timestamp")


def test_detect_outliers_handles_short_and_constant_series() -> None:
    short = pd.DataFrame({"close": [100.0, 101.0]})
    constant = pd.DataFrame({"close": [100.0, 100.0, 100.0, 100.0]})

    short_result = _detect_outliers(short, 3.0)
    constant_result = _detect_outliers(constant, 3.0)

    assert short_result.eq(False).all()
    assert constant_result.eq(False).all()
