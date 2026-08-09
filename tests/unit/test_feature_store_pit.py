"""Point-in-time Feature Store leak tests (P0 T003).

Guarantees:
- compute_features(end=T) never sees raw bars with timestamp > T
- load_features(end=T) never returns feature rows with timestamp > T
- as-of meta path (when injected) also respects the cutoff
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from quantflow.data.feature_store import FeatureStore
from quantflow.data.store import DataStore


class _RecordingComputer:
    """Records the raw frame seen by compute_all for leak assertions."""

    def __init__(self) -> None:
        self.last_df: pd.DataFrame | None = None

    def compute_all(
        self, df: pd.DataFrame, indicator_names: list[str] | None = None
    ) -> pd.DataFrame:
        self.last_df = df.copy()
        out = df.copy()
        out["fake_ind"] = 1.0
        return out


class _MetaStub:
    def compute_meta_features(
        self,
        features: pd.DataFrame,
        funding: pd.DataFrame,
        open_interest: pd.DataFrame,
    ) -> pd.DataFrame:
        out = features.copy()
        out["meta_n_funding"] = len(funding)
        out["meta_n_oi"] = len(open_interest)
        out["meta_max_funding_ts"] = (
            int(funding["timestamp"].max()) if not funding.empty else -1
        )
        return out


def _seed_ohlcv(raw_store: DataStore, symbol: str = "BTC/USDT", n: int = 48) -> list[int]:
    # Hourly bars starting 2024-01-01 UTC.
    start = pd.Timestamp("2024-01-01", tz="UTC")
    stamps = [int((start + pd.Timedelta(hours=i)).timestamp() * 1000) for i in range(n)]
    df = pd.DataFrame(
        {
            "timestamp": stamps,
            "open": np.linspace(100, 120, n),
            "high": np.linspace(101, 121, n),
            "low": np.linspace(99, 119, n),
            "close": np.linspace(100.5, 120.5, n),
            "volume": np.full(n, 10.0),
        }
    )
    raw_store.save(df, symbol)
    return stamps


class TestFeatureStorePIT:
    def test_compute_features_no_future_raw_bars(self, tmp_path):
        raw = DataStore(str(tmp_path / "raw"))
        stamps = _seed_ohlcv(raw)
        cutoff = stamps[23]  # mid series
        computer = _RecordingComputer()
        fs = FeatureStore(str(tmp_path / "feat"), indicator_computer=computer)

        features = fs.compute_features("BTC/USDT", cutoff, [], raw_store=raw)
        assert not features.empty
        assert computer.last_df is not None
        max_ts = int(computer.last_df["timestamp"].astype("int64").max())
        assert max_ts <= cutoff
        # Future bars exist in store but must not appear.
        assert max_ts < stamps[-1]
        assert int(features["computed_at"].iloc[0]) == cutoff

    def test_load_features_respects_end_cutoff(self, tmp_path):
        fs = FeatureStore(str(tmp_path / "feat"), indicator_computer=_RecordingComputer())
        stamps = [
            int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000),
            int(pd.Timestamp("2024-01-02", tz="UTC").timestamp() * 1000),
            int(pd.Timestamp("2024-01-03", tz="UTC").timestamp() * 1000),
        ]
        feats = pd.DataFrame(
            {
                "timestamp": stamps,
                "datetime": pd.to_datetime(stamps, unit="ms", utc=True),
                "fake_ind": [1.0, 2.0, 3.0],
            }
        )
        fs.save_features("BTC/USDT", feats)
        loaded = fs.load_features("BTC/USDT", end=stamps[1])
        assert not loaded.empty
        assert int(loaded["timestamp"].astype("int64").max()) <= stamps[1]
        assert len(loaded) == 2

    def test_meta_asof_respects_cutoff(self, tmp_path):
        raw = DataStore(str(tmp_path / "raw"))
        stamps = _seed_ohlcv(raw)
        cutoff = stamps[20]

        class _MetaStore:
            def query_funding_rates(self, symbol: str, end: int | None = None) -> pd.DataFrame:
                # Include a future funding row that must be filtered by FeatureStore/meta_store.
                all_ts = stamps[:30] + [stamps[-1] + 3_600_000]
                df = pd.DataFrame(
                    {
                        "timestamp": all_ts,
                        "funding_rate": np.zeros(len(all_ts)),
                    }
                )
                if end is not None:
                    df = df[df["timestamp"] <= end]
                return df

            def query_open_interest(self, symbol: str, end: int | None = None) -> pd.DataFrame:
                df = pd.DataFrame({"timestamp": stamps[:30], "open_interest": np.ones(30)})
                if end is not None:
                    df = df[df["timestamp"] <= end]
                return df

        computer = _RecordingComputer()
        fs = FeatureStore(
            str(tmp_path / "feat"),
            indicator_computer=computer,
            meta_computer=_MetaStub(),
        )
        features = fs.compute_features(
            "BTC/USDT",
            cutoff,
            [],
            raw_store=raw,
            meta_store=_MetaStore(),  # type: ignore[arg-type]
        )
        assert "meta_max_funding_ts" in features.columns
        max_funding = int(features["meta_max_funding_ts"].iloc[-1])
        assert max_funding <= cutoff
