"""IMP-03: PIT audit helper tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.data.feature_store import FeatureStore
from quantflow.data.pit_audit import (
    PITAuditError,
    audit_frame_no_future,
    intentional_leak_frame,
    run_pit_audit_suite,
)
from quantflow.data.store import DataStore


class _RecordingComputer:
    def __init__(self) -> None:
        self.last_df = None

    def compute_all(self, df: pd.DataFrame, indicator_names: list[str] | None = None):
        self.last_df = df.copy()
        out = df.copy()
        out["fake_ind"] = 1.0
        return out


def _seed(raw: DataStore, n: int = 40) -> list[int]:
    start = pd.Timestamp("2024-01-01", tz="UTC")
    stamps = [int((start + pd.Timedelta(hours=i)).timestamp() * 1000) for i in range(n)]
    df = pd.DataFrame(
        {
            "timestamp": stamps,
            "open": np.linspace(100, 110, n),
            "high": np.linspace(101, 111, n),
            "low": np.linspace(99, 109, n),
            "close": np.linspace(100.5, 110.5, n),
            "volume": np.full(n, 5.0),
        }
    )
    raw.save(df, "BTC/USDT")
    return stamps


def test_audit_frame_detects_future() -> None:
    stamps = [1_000, 2_000, 3_000]
    leak = intentional_leak_frame(stamps, cutoff_ms=2_000)
    bad = audit_frame_no_future(leak, cutoff_ms=2_000, scope="leak")
    assert bad.passed is False
    with pytest.raises(PITAuditError):
        bad.raise_if_failed()

    clean = leak[leak["timestamp"] <= 2_000]
    ok = audit_frame_no_future(clean, cutoff_ms=2_000)
    assert ok.passed is True


def test_suite_passes_on_honest_store(tmp_path) -> None:
    raw = DataStore(str(tmp_path / "raw"))
    stamps = _seed(raw)
    cutoff = stamps[20]
    fs = FeatureStore(str(tmp_path / "feat"), indicator_computer=_RecordingComputer())
    result = run_pit_audit_suite(
        fs,
        symbol="BTC/USDT",
        cutoff_ms=cutoff,
        raw_store=raw,
        also_load=False,
    )
    assert result.passed is True
    result.raise_if_failed()
