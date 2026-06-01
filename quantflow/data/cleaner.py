"""Data cleaner — OHLCV data cleaning, outlier detection, and validation."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def clean_ohlcv(
    df: pd.DataFrame,
    remove_outliers: bool = True,
    outlier_std: float = 5.0,
    fill_method: str = "ffill",
    validate_no_future_leak: bool = True,
) -> pd.DataFrame:
    """Clean OHLCV data: remove outliers, fill gaps, validate integrity.

    Args:
        df: DataFrame with columns [timestamp, open, high, low, close, volume].
        remove_outliers: Whether to detect and mark outlier prices.
        outlier_std: Number of standard deviations for outlier detection.
        fill_method: Method for filling missing values ('ffill', 'interpolate').
        validate_no_future_leak: Validate that timestamps are not from the future.

    Returns:
        Cleaned DataFrame with additional 'is_outlier' column if remove_outliers=True.
    """
    if df.empty:
        return df

    df = df.copy()

    # Ensure timestamp column is datetime
    if "timestamp" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    if "datetime" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["datetime"]):
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True)

    # Sort by timestamp
    sort_col = "timestamp" if "timestamp" in df.columns else "datetime"
    if sort_col in df.columns:
        df = df.sort_values(sort_col).reset_index(drop=True)

    # Validate no future leak
    if validate_no_future_leak:
        _validate_no_future_leak(df, sort_col)

    # Remove duplicates
    before = len(df)
    if sort_col in df.columns:
        df = df.drop_duplicates(subset=[sort_col], keep="last")
    after = len(df)
    if before != after:
        logger.info("Removed %d duplicate rows", before - after)

    # Fill missing values
    price_cols = [c for c in ["open", "high", "low", "close"] if c in df.columns]
    for col in price_cols:
        if df[col].isna().any():
            if fill_method == "ffill":
                df[col] = df[col].ffill()
            elif fill_method == "interpolate":
                df[col] = df[col].interpolate(method="linear")
            logger.info("Filled %d missing values in %s", df[col].isna().sum(), col)

    # Volume: fill NaN with 0
    if "volume" in df.columns and df["volume"].isna().any():
        df["volume"] = df["volume"].fillna(0)

    # Outlier detection
    if remove_outliers and "close" in df.columns:
        df["is_outlier"] = _detect_outliers(df, outlier_std)
        n_outliers = df["is_outlier"].sum()
        if n_outliers > 0:
            logger.warning("Detected %d outlier rows (>%d std)", n_outliers, outlier_std)
            # Replace outlier prices with previous valid close
            for col in price_cols:
                df.loc[df["is_outlier"], col] = np.nan
                df[col] = df[col].ffill()

    # Validate OHLC relationships
    if all(c in df.columns for c in ["open", "high", "low", "close"]):
        invalid_ohlc = (
            (df["high"] < df["low"])
            | (df["high"] < df["open"])
            | (df["high"] < df["close"])
            | (df["low"] > df["open"])
            | (df["low"] > df["close"])
        )
        n_invalid = invalid_ohlc.sum()
        if n_invalid > 0:
            logger.warning("Found %d rows with invalid OHLC relationships", n_invalid)
            # Fix: adjust high/low to encompass open/close
            df.loc[invalid_ohlc, "high"] = df.loc[invalid_ohlc, ["open", "high", "low", "close"]].max(axis=1)
            df.loc[invalid_ohlc, "low"] = df.loc[invalid_ohlc, ["open", "high", "low", "close"]].min(axis=1)

    return df


def validate_no_future_leak(df: pd.DataFrame, cutoff_timestamp: int | None = None) -> bool:
    """Validate that no data beyond cutoff_timestamp exists (for backtest safety).

    Args:
        df: DataFrame to check.
        cutoff_timestamp: Maximum allowed timestamp. If None, uses current time.

    Returns:
        True if no future data leak detected, False otherwise.
    """
    import time

    if cutoff_timestamp is None:
        cutoff_timestamp = int(time.time() * 1000)

    for col in ["timestamp", "datetime"]:
        if col not in df.columns:
            continue

        ts = df[col]
        if col == "datetime" and pd.api.types.is_datetime64_any_dtype(ts):
            # Convert datetime to ms timestamp for comparison
            ts_ms = ts.astype("int64") // 10**6
            if ts_ms.max() > cutoff_timestamp:
                logger.error("Future data leak in datetime column: max=%d > cutoff=%d",
                             ts_ms.max(), cutoff_timestamp)
                return False
        elif col == "timestamp":
            max_ts = ts.max()
            if max_ts > cutoff_timestamp:
                logger.error("Future data leak in timestamp column: max=%d > cutoff=%d",
                             max_ts, cutoff_timestamp)
                return False

    return True


def _validate_no_future_leak(df: pd.DataFrame, sort_col: str) -> None:
    """Validate that no timestamps are from the future."""
    if sort_col not in df.columns:
        return

    ts = df[sort_col]
    if not pd.api.types.is_datetime64_any_dtype(ts):
        return

    now = pd.Timestamp.now(tz="UTC")
    future_mask = ts > now
    n_future = future_mask.sum()
    if n_future > 0:
        logger.warning("Found %d rows with future timestamps — possible data leak!", n_future)
        raise ValueError(
            f"Future data detected: {n_future} rows have timestamps after {now}. "
            "This may indicate a data leak. Set validate_no_future_leak=False to skip."
        )


def _detect_outliers(df: pd.DataFrame, n_std: float) -> pd.Series:
    """Detect outlier rows using z-score on returns.

    Returns a boolean Series where True indicates an outlier.
    """
    if "close" not in df.columns or len(df) < 3:
        return pd.Series(False, index=df.index)

    returns = df["close"].pct_change()
    mean = returns.mean()
    std = returns.std()

    if std == 0 or pd.isna(std):
        return pd.Series(False, index=df.index)

    z_scores = (returns - mean).abs() / std
    return z_scores > n_std
