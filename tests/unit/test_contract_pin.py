"""T011: research contract window pin + data fingerprint."""

from __future__ import annotations

import warnings

import pandas as pd
import pytest

from quantflow.strategy.research.contract_pin import (
    ContractPinError,
    build_window_pin,
    fingerprint_ohlcv,
    fingerprint_universe,
    parse_window_ms,
    warn_if_unpinned,
)


def _bars(n: int = 10, start_ms: int = 1_600_000_000_000) -> pd.DataFrame:
    stamps = [start_ms + i * 3_600_000 for i in range(n)]
    return pd.DataFrame(
        {
            "timestamp": stamps,
            "open": [100.0 + i for i in range(n)],
            "high": [101.0 + i for i in range(n)],
            "low": [99.0 + i for i in range(n)],
            "close": [100.5 + i for i in range(n)],
            "volume": [1.0] * n,
        }
    )


def test_parse_window_iso():
    start_ms, end_ms = parse_window_ms("2021-01-01", "2026-08-04")
    assert start_ms < end_ms
    # 2021-01-01T00:00:00Z
    assert start_ms == 1609459200000


def test_parse_window_rejects_inverted():
    with pytest.raises(ContractPinError):
        parse_window_ms("2026-01-01", "2020-01-01")


def test_fingerprint_stable():
    df = _bars()
    a = fingerprint_ohlcv(df)
    b = fingerprint_ohlcv(df.copy())
    assert a == b
    assert len(a) == 16


def test_fingerprint_changes_with_data():
    df = _bars()
    other = df.copy()
    other.loc[0, "close"] = 999.0
    assert fingerprint_ohlcv(df) != fingerprint_ohlcv(other)


def test_fingerprint_universe_aggregate():
    frames = {"BTC/USDT": _bars(), "ETH/USDT": _bars(start_ms=1_600_000_000_000)}
    block = fingerprint_universe(frames)
    assert "aggregate" in block
    assert set(block["symbols"]) == {"BTC/USDT", "ETH/USDT"}
    assert block["symbols"]["BTC/USDT"]["bar_count"] == 10


def test_build_window_pin():
    frames = {"BTC/USDT": _bars()}
    pin = build_window_pin(
        start="2020-09-13",
        end="2020-09-14",
        frames=frames,
        timeframe="1h",
    )
    d = pin.to_dict()
    assert d["start_ms"] < d["end_ms"]
    assert d["data_fingerprint"]["aggregate"]


def test_warn_if_unpinned_require():
    with pytest.raises(ContractPinError):
        warn_if_unpinned(None, None, require_pin=True, context="unit")


def test_warn_if_unpinned_soft():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        warn_if_unpinned("", "", require_pin=False, context="unit")
        assert any("T011" in str(x.message) for x in w)
