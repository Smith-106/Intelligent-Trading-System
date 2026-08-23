"""Multi-timeframe resampling layer (PERF-REV015).

Exchanges natively serve only a coarse bar vocabulary (OKX: 1m..1d, no
45m/3h/5h/7h/16h/32h). The 24-timeframe analysis requirement is therefore
met by storing two base grids — 5m for intraday, 1d for multi-day — and
deriving everything else locally with a pure, deterministic aggregation.

Design contract (from the perf_data audit):
- anchor: UTC epoch floor division (never the first bar's timestamp — that
  drifts with the data window and breaks idempotency);
- mapping: open=first, close=last, high=max, low=min, volume=sum,
  timestamp=bucket left edge;
- leak-safe: the trailing bucket is dropped unless its close time is fully
  covered by base bars already closed;
- sparse: missing sub-bars shrink the bucket instead of erroring; derived
  frames are never cleaner-filled (no synthetic prices);
- idempotent: same base frame -> byte-identical derived frame.
"""

from __future__ import annotations

import re

import pandas as pd

__all__ = [
    "ANALYSIS_TIMEFRAMES",
    "BASE_TIMEFRAMES",
    "base_timeframe_for",
    "resample_ohlcv",
    "timeframe_to_timedelta",
]

#: The full analysis vocabulary requested for simultaneous multi-TF analysis.
ANALYSIS_TIMEFRAMES: tuple[str, ...] = (
    "5m", "10m", "15m", "30m", "45m",
    "1h", "2h", "3h", "5h", "6h", "7h", "8h", "12h", "16h",
    "24h", "32h",
    "2d", "3d", "5d", "7d", "10d", "15d", "30d",
)

#: Base grids that are actually downloaded and persisted. Every analysis
#: timeframe is an exact multiple of exactly one base, so two download
#: chains per symbol cover all 24 buckets with zero gaps.
BASE_TIMEFRAMES: tuple[str, ...] = ("5m", "1d")

_TF_RE = re.compile(r"^(\d+)([mhd])$")
_UNIT_MS = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}


def timeframe_to_ms(timeframe: str) -> int:
    """Convert a ``<n><m|h|d>`` timeframe to its duration in milliseconds."""
    m = _TF_RE.match(timeframe)
    if not m or int(m.group(1)) <= 0:
        raise ValueError(f"Invalid timeframe: {timeframe!r}")
    return int(m.group(1)) * _UNIT_MS[m.group(2)]


def timeframe_to_timedelta(timeframe: str) -> pd.Timedelta:
    return pd.Timedelta(timeframe_to_ms(timeframe), unit="ms")


def base_timeframe_for(timeframe: str) -> str:
    """Return the base grid a given analysis timeframe derives from.

    Intraday buckets derive from 5m, multi-day from 1d. Raises for
    non-multiples (would produce misaligned or lossy buckets).
    """
    ms = timeframe_to_ms(timeframe)
    if ms % _UNIT_MS["d"] == 0:
        return "1d"
    if ms % _UNIT_MS["m"] == 0 and ms % timeframe_to_ms("5m") == 0:
        return "5m"
    raise ValueError(f"Timeframe {timeframe!r} is not derivable from {BASE_TIMEFRAMES}")


def resample_ohlcv(base: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Aggregate a base-grid OHLCV frame up to ``timeframe``.

    Pure function of the input frame. See module docstring for the
    correctness contract.
    """
    period = timeframe_to_timedelta(timeframe)
    if base.empty:
        return base.iloc[0:0].copy()

    df = base.sort_values("timestamp")
    # Floor the bar-open timestamps onto fixed UTC bucket edges.
    bucket = (df["timestamp"].astype("int64") // timeframe_to_ms(timeframe)) * timeframe_to_ms(
        timeframe
    )

    grouped = df.assign(_bucket=bucket).groupby("_bucket", sort=True)
    out = pd.DataFrame(
        {
            # bucket left edge (UTC floor), NOT the first bar's timestamp —
            # base grids may start mid-bucket.
            "timestamp": grouped["_bucket"].first().values,
            "open": grouped["open"].first().values,
            "high": grouped["high"].max().values,
            "low": grouped["low"].min().values,
            "close": grouped["close"].last().values,
            "volume": grouped["volume"].sum().values,
        }
    )

    # Leak-safe: drop the trailing bucket when its window is not fully
    # covered by closed base bars (e.g. a 32h bucket seen after only 10h of
    # bars would otherwise present a partial candle as final). The last base
    # bar opening at t closes at t + base_period; derive the period from the
    # observed minimum spacing (robust to gaps).
    if len(df) >= 2:
        spacing = int(df["timestamp"].diff().dropna().min())
        base_period = max(spacing, 1)
    else:
        base_period = timeframe_to_ms(timeframe)
    last_close = int(df["timestamp"].iloc[-1]) + base_period
    while len(out) > 0 and int(out["timestamp"].iloc[-1]) + timeframe_to_ms(timeframe) > last_close:
        out = out.iloc[:-1]

    out["datetime"] = pd.to_datetime(out["timestamp"], unit="ms", utc=True)
    return out.reset_index(drop=True)
