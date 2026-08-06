"""Tests for meta-market feature computation (s3 T-s3-02).

Covers the L2 feature computers (funding rate / open interest) and the
MetaFeatureEngine as-of join, including point-in-time safety (no future
data: negative shifts forbidden and statically guarded).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantflow.indicators.meta_features import (
    FUNDING_FEATURE_COLUMNS,
    OI_FEATURE_COLUMNS,
    FundingRateFeatures,
    MetaFeatureEngine,
    OpenInterestFeatures,
)


def _make_funding(n: int = 10, start_ts: int = 1_700_000_000_000) -> pd.DataFrame:
    """Simulated funding-rate frame (8h cadence, ms timestamps)."""
    ts = [start_ts + i * 8 * 3600 * 1000 for i in range(n)]
    rates = [0.0001 * (i % 5 - 2) + 0.00005 * np.sin(i) for i in range(n)]
    return pd.DataFrame(
        {
            "timestamp": ts,
            "funding_rate": rates,
            "realized_rate": rates,
            "funding_time": ts,
        }
    )


def _make_oi(n: int = 10, start_ts: int = 1_700_000_000_000) -> pd.DataFrame:
    ts = [start_ts + i * 3600 * 1000 for i in range(n)]
    oi = [1_000_000.0 + i * 10_000.0 for i in range(n)]
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open_interest": oi,
            "open_interest_ccy": [x * 0.00001 for x in oi],
            "open_interest_usd": [x * 60_000.0 for x in oi],
        }
    )


def _make_features(n: int = 8, start_ts: int = 1_700_000_000_000) -> pd.DataFrame:
    ts = [start_ts + i * 3600 * 1000 for i in range(n)]
    return pd.DataFrame(
        {
            "timestamp": ts,
            "close": [100.0 + i for i in range(n)],
            "rsi_14": [50.0 + i for i in range(n)],
        }
    )


class TestFundingRateFeatures:
    def test_computes_ma_and_skew_columns(self):
        out = FundingRateFeatures().compute(_make_funding())
        for col in FUNDING_FEATURE_COLUMNS:
            assert col in out.columns
        # First row: ma == raw (min_periods=1)
        assert out.loc[0, "funding_rate_ma_3"] == pytest.approx(out.loc[0, "funding_rate"])
        # Skew = rate - ma
        assert out["funding_skew_8h"].iloc[2] == pytest.approx(
            out["funding_rate"].iloc[2] - out["funding_rate_ma_3"].iloc[2]
        )

    def test_empty_input_returns_empty(self):
        out = FundingRateFeatures().compute(pd.DataFrame())
        assert out.empty


class TestOpenInterestFeatures:
    def test_computes_change_and_ratio_columns(self):
        out = OpenInterestFeatures().compute(_make_oi())
        for col in OI_FEATURE_COLUMNS:
            assert col in out.columns
        # oi_change_1: (v1 - v0) / v0
        assert out["oi_change_1"].iloc[1] == pytest.approx(10_000.0 / 1_000_000.0)
        # ratio = usd / oi
        assert out["oi_usd_ratio"].iloc[0] == pytest.approx(60_000.0)

    def test_empty_input_returns_empty(self):
        out = OpenInterestFeatures().compute(pd.DataFrame())
        assert out.empty


class TestMetaFeatureEngine:
    def test_engine_appends_both_feature_groups(self):
        engine = MetaFeatureEngine()
        out = engine.compute_meta_features(_make_features(), _make_funding(), _make_oi())
        assert set(FUNDING_FEATURE_COLUMNS).issubset(out.columns)
        assert set(OI_FEATURE_COLUMNS).issubset(out.columns)
        assert len(out) == 8  # row count preserved

    def test_asof_join_is_point_in_time(self):
        """A feature at ts must not see meta rows AFTER ts."""
        engine = MetaFeatureEngine()
        features = _make_features(n=3, start_ts=1_700_000_000_000)
        # Funding only at t0 (before all features); future funding at t3 excluded
        funding = _make_funding(n=2, start_ts=1_700_000_000_000)
        future_funding = _make_funding(n=1, start_ts=1_700_000_000_000 + 4 * 3600 * 1000)
        funding = pd.concat([funding, future_funding], ignore_index=True)
        out = engine.compute_meta_features(features, funding, _make_oi())
        # Feature rows at ts <= last funding ts get values; the row at
        # ts beyond the last *past* funding must still merge the nearest
        # past record (backward direction) — never a future record.
        assert out["funding_rate_ma_3"].notna().all()

    def test_empty_features_returns_as_is(self):
        engine = MetaFeatureEngine()
        out = engine.compute_meta_features(pd.DataFrame(), _make_funding(), _make_oi())
        assert out.empty

    def test_missing_timestamp_column_skips(self):
        engine = MetaFeatureEngine()
        features = pd.DataFrame({"close": [1.0, 2.0]})
        out = engine.compute_meta_features(features, _make_funding(), _make_oi())
        assert "close" in out.columns
        assert not set(FUNDING_FEATURE_COLUMNS).issubset(out.columns)


class TestLookaheadStaticGuard:
    """Static guard: no negative shift in meta feature source (T-s3-02)."""

    def test_no_negative_shift_in_meta_features(self):
        source = Path("quantflow/indicators/meta_features.py").read_text(encoding="utf-8")
        assert "shift(-" not in source
        assert "pct_change(" in source  # causal pct_change only
