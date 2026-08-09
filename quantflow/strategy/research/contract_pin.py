"""Research contract time-window pin + data fingerprint (T011).

Locks the *interpretation* of a research run to:

- ISO calendar ``start`` / ``end`` (contract text)
- millisecond bounds ``start_ms`` / ``end_ms``
- a content fingerprint of the OHLCV bars actually used

So growing parquet after ``end`` cannot silently change a sealed GO narrative
when scripts re-query with the same pin.
"""

from __future__ import annotations

import hashlib
import json
import logging
import warnings
from dataclasses import asdict, dataclass
from typing import Any, Mapping

import pandas as pd

logger = logging.getLogger(__name__)

OHLCV_COLS = ("timestamp", "open", "high", "low", "close", "volume")


class ContractPinError(ValueError):
    """Invalid or missing research pin."""


def parse_window_ms(
    start: str | int | float,
    end: str | int | float,
) -> tuple[int, int]:
    """Parse contract start/end to inclusive UTC millisecond bounds.

    Accepts ISO date/datetime strings (``YYYY-MM-DD`` or full ISO) or epoch ms.
    """
    start_ms = _to_ms(start, role="start")
    end_ms = _to_ms(end, role="end")
    if end_ms < start_ms:
        raise ContractPinError(f"end_ms ({end_ms}) < start_ms ({start_ms})")
    return start_ms, end_ms


def _to_ms(value: str | int | float, *, role: str) -> int:
    if isinstance(value, bool):
        raise ContractPinError(f"{role} must be date string or epoch ms, not bool")
    if isinstance(value, (int, float)):
        v = int(value)
        # Heuristic: seconds vs ms
        if v < 10_000_000_000:
            return v * 1000
        return v
    text = str(value).strip()
    if not text:
        raise ContractPinError(f"{role} is empty")
    if text.isdigit():
        return _to_ms(int(text), role=role)
    ts = pd.Timestamp(text, tz="UTC")
    return int(ts.timestamp() * 1000)


def fingerprint_ohlcv(df: pd.DataFrame) -> str:
    """Stable short hash of OHLCV rows (order by timestamp).

    Empty frame → ``empty``. Missing OHLCV columns are ignored (still hashes
    available columns + length).
    """
    if df is None or len(df) == 0:
        return "empty"
    cols = [c for c in OHLCV_COLS if c in df.columns]
    if not cols:
        cols = list(df.columns[:6])
    ordered = df.sort_values("timestamp") if "timestamp" in df.columns else df
    # Round floats so minor storage noise does not thrash the pin across platforms.
    payload: dict[str, Any] = {"n": int(len(ordered)), "cols": cols}
    for c in cols:
        series = ordered[c]
        if c == "timestamp" or series.dtype.kind in "iu":
            payload[c] = series.astype("int64").tolist()
        else:
            payload[c] = [round(float(x), 8) if pd.notna(x) else None for x in series]
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def fingerprint_universe(
    frames: Mapping[str, pd.DataFrame],
) -> dict[str, Any]:
    """Per-symbol fingerprints + aggregate id for a multi-symbol window."""
    per: dict[str, dict[str, Any]] = {}
    parts: list[str] = []
    for sym in sorted(frames.keys()):
        df = frames[sym]
        fp = fingerprint_ohlcv(df)
        n = int(len(df)) if df is not None else 0
        ts_min = ts_max = None
        if df is not None and n > 0 and "timestamp" in df.columns:
            ts = df["timestamp"].astype("int64")
            ts_min = int(ts.min())
            ts_max = int(ts.max())
        per[sym] = {
            "fingerprint": fp,
            "bar_count": n,
            "start_ms": ts_min,
            "end_ms": ts_max,
        }
        parts.append(f"{sym}:{fp}:{n}")
    aggregate = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return {
        "aggregate": aggregate,
        "symbols": per,
        "symbol_count": len(per),
    }


@dataclass(frozen=True)
class WindowPin:
    """Resolved contract window + fingerprint block."""

    start: str
    end: str
    start_ms: int
    end_ms: int
    timeframe: str
    data_fingerprint: dict[str, Any]
    require_pin: bool = True

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def build_window_pin(
    *,
    start: str | int | float,
    end: str | int | float,
    frames: Mapping[str, pd.DataFrame],
    timeframe: str = "1h",
    require_pin: bool = True,
) -> WindowPin:
    """Build pin metadata from contract strings and loaded frames."""
    start_s = str(start)
    end_s = str(end)
    if require_pin and (not start_s or not end_s):
        raise ContractPinError("require_pin=True but start/end missing")
    start_ms, end_ms = parse_window_ms(start, end)
    fp = fingerprint_universe(frames)
    return WindowPin(
        start=start_s,
        end=end_s,
        start_ms=start_ms,
        end_ms=end_ms,
        timeframe=timeframe,
        data_fingerprint=fp,
        require_pin=require_pin,
    )


def warn_if_unpinned(
    start: str | None,
    end: str | None,
    *,
    require_pin: bool = False,
    context: str = "research run",
) -> None:
    """WARN or fail when a research entrypoint lacks an explicit window.

    Baseline-0 always pins; free-form scripts may omit — T011 makes that loud.
    """
    missing = not (start and end)
    if not missing:
        return
    msg = (
        f"{context}: no explicit start/end pin — results may drift as parquet grows "
        "(T011). Pass --start/--end or set require_pin."
    )
    if require_pin:
        raise ContractPinError(msg)
    warnings.warn(msg, UserWarning, stacklevel=2)
    logger.warning(msg)


def load_and_fingerprint_symbols(
    store: Any,
    symbols: list[str],
    *,
    start_ms: int,
    end_ms: int,
    timeframe: str = "1h",
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    """Query store for each symbol in [start_ms, end_ms] and fingerprint.

    Returns (frames, fingerprint_block). Empty symbols are omitted from frames.
    """
    frames: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = store.query(sym, start=start_ms, end=end_ms, timeframe=timeframe)
        if df is None or df.empty:
            continue
        cols = [c for c in OHLCV_COLS if c in df.columns]
        frames[sym] = df[cols].reset_index(drop=True) if cols else df.reset_index(drop=True)
    return frames, fingerprint_universe(frames)
