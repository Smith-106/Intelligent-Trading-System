"""Lightweight public-trades persistence (W22a).

Hive layout under ``base_dir``::

    trades/{SYMBOL}/year=YYYY/month=MM.parquet

Columns: timestamp, price, amount, side.

Not a full tape warehouse — research scaffold for true CVD. Market data
dumps stay local (gitignore data/trades/ if large).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from quantflow.common.exceptions import DataError
from quantflow.common.validators import validate_symbol

logger = logging.getLogger(__name__)

TRADE_COLS = ("timestamp", "price", "amount", "side")


class TradesStore:
    """Append-friendly Parquet store for recent trades."""

    def __init__(self, base_dir: str | Path = "data/trades") -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def save_trades(self, symbol: str, trades: pd.DataFrame) -> int:
        """Persist trades; returns rows written after dedupe by timestamp+side+price."""
        if trades is None or trades.empty:
            return 0
        sym = validate_symbol(symbol)
        df = trades.copy()
        for col in TRADE_COLS:
            if col not in df.columns:
                raise DataError(f"trades missing column {col!r}")
        df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce").astype("int64")
        df["price"] = pd.to_numeric(df["price"], errors="coerce").astype(float)
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").astype(float)
        df["side"] = df["side"].astype(str)
        df = df.dropna(subset=["timestamp", "price", "amount"])
        if df.empty:
            return 0
        dt = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df["year"] = dt.dt.year
        df["month"] = dt.dt.month
        written = 0
        for (year, month), group in df.groupby(["year", "month"]):
            year_dir = self._base / sym / f"year={int(year)}"
            year_dir.mkdir(parents=True, exist_ok=True)
            path = year_dir / f"month={int(month):02d}.parquet"
            existing = pd.read_parquet(path) if path.exists() else pd.DataFrame()
            combined = pd.concat([existing, group[list(TRADE_COLS)]], ignore_index=True)
            before = len(combined)
            combined = combined.drop_duplicates(
                subset=["timestamp", "price", "amount", "side"], keep="first"
            ).sort_values("timestamp")
            combined.to_parquet(path, index=False, compression="zstd")
            written += len(combined) - (before - len(group))
            # simpler accounting: count group rows after merge
        logger.info("TradesStore saved trades for %s (%d input rows)", symbol, len(df))
        return len(df)

    def load_trades(
        self,
        symbol: str,
        start: int | None = None,
        end: int | None = None,
    ) -> pd.DataFrame:
        """Load trades; empty DataFrame when none."""
        sym = validate_symbol(symbol)
        root = self._base / sym
        if not root.exists():
            return pd.DataFrame(columns=list(TRADE_COLS))
        paths = list(root.glob("year=*/month=*.parquet"))
        if not paths:
            return pd.DataFrame(columns=list(TRADE_COLS))
        frames = [pd.read_parquet(p) for p in paths]
        df = pd.concat(frames, ignore_index=True)
        if "timestamp" not in df.columns:
            return pd.DataFrame(columns=list(TRADE_COLS))
        df = df.sort_values("timestamp").reset_index(drop=True)
        if start is not None:
            df = df[df["timestamp"] >= int(start)]
        if end is not None:
            df = df[df["timestamp"] <= int(end)]
        return df[list(TRADE_COLS)].reset_index(drop=True)


def build_cvd_feature_frame(
    ohlcv: pd.DataFrame,
    trades: pd.DataFrame | None = None,
    *,
    prefer_trades: bool = True,
) -> pd.DataFrame:
    """Build a feature frame with ``cvd`` + provenance for FeatureStore.

    - If trades present and ``prefer_trades``: bar-bucketed true-ish CVD via
      trade signs (last cumulative value at each bar timestamp).
    - Else: ``cvd_proxy`` from close/volume (W20b).

    Fail-closed: never invent trades. Output always has ``timestamp`` + ``cvd``
    + ``cvd_source`` ∈ {trades, proxy, empty}.
    """
    from quantflow.common.cvd import cvd_from_trades, cvd_proxy

    if ohlcv is None or ohlcv.empty:
        return pd.DataFrame(columns=["timestamp", "cvd", "cvd_source"])

    out = ohlcv.copy()
    if "timestamp" not in out.columns:
        raise DataError("ohlcv must include timestamp for CVD features")

    has_trades = (
        prefer_trades
        and trades is not None
        and not trades.empty
        and all(c in trades.columns for c in ("timestamp", "price", "amount", "side"))
    )
    if has_trades:
        t = trades.sort_values("timestamp")
        cvd_line = cvd_from_trades(t["price"], t["amount"], t["side"])
        # Align last trade-CVD observed at or before each bar timestamp
        bar_ts = out["timestamp"].astype("int64").to_numpy()
        trade_ts = t["timestamp"].astype("int64").to_numpy()
        cvd_vals = cvd_line.to_numpy()
        aligned: list[float] = []
        j = -1
        n_t = len(trade_ts)
        for bt in bar_ts:
            while j + 1 < n_t and trade_ts[j + 1] <= bt:
                j += 1
            aligned.append(float(cvd_vals[j]) if j >= 0 else 0.0)
        out["cvd"] = aligned
        out["cvd_source"] = "trades"
    elif "close" in out.columns and "volume" in out.columns:
        out["cvd"] = cvd_proxy(out["close"], out["volume"])
        out["cvd_source"] = "proxy"
    else:
        out["cvd"] = float("nan")
        out["cvd_source"] = "empty"

    cols = ["timestamp", "cvd", "cvd_source"]
    # keep optional ohlcv helpers if present
    for c in ("open", "high", "low", "close", "volume"):
        if c in out.columns and c not in cols:
            cols.append(c)
    return out[cols]


def save_cvd_features(
    feature_store: Any,
    symbol: str,
    ohlcv: pd.DataFrame,
    trades: pd.DataFrame | None = None,
    *,
    prefer_trades: bool = True,
) -> pd.DataFrame:
    """Compute CVD features and write via FeatureStore.save_features."""
    frame = build_cvd_feature_frame(ohlcv, trades, prefer_trades=prefer_trades)
    if not frame.empty:
        feature_store.save_features(symbol, frame)
    return frame
