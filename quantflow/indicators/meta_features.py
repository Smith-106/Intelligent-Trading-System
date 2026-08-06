"""Meta-market feature computation — funding rate / open interest derived features.

s3-ai-research-pipeline (wave2, T-s3-02): FeatureStore gains funding-rate and
open-interest feature sources on top of OHLCV indicators. To respect the
six-layer one-way dependency (L1 data/ must not import L2 indicators/), this
module lives in L2 (indicators/) and is *injected* into FeatureStore via the
``IndicatorComputer`` Protocol seam — exactly like ``IndicatorEngine``.

Point-in-time safety: every computation here only uses rows ``<= timestamp``
of the meta frame passed in (FeatureStore queries meta sources with
``end=timestamp`` before calling), and no negative ``shift()`` is used
(negative shift would pull future values into the present — forbidden).
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

import pandas as pd

logger = logging.getLogger(__name__)

#: Feature column names emitted by the funding-rate computer.
FUNDING_FEATURE_COLUMNS = ("funding_rate_ma_3", "funding_rate_abs_ma_3", "funding_skew_8h")
#: Feature column names emitted by the open-interest computer.
OI_FEATURE_COLUMNS = ("oi_change_1", "oi_change_3", "oi_usd_ratio")


@runtime_checkable
class MetaFeatureComputer(Protocol):
    """Contract for meta-market feature computation (L2 seam for FeatureStore).

    Mirrors :class:`quantflow.common.indicator_protocol.IndicatorComputer`: a
    concrete L2 implementation is injected into FeatureStore; L1 never
    imports L2 directly.
    """

    def compute_meta_features(
        self,
        features: pd.DataFrame,
        funding: pd.DataFrame,
        open_interest: pd.DataFrame,
    ) -> pd.DataFrame:
        """Return ``features`` with meta feature columns appended.

        ``funding`` / ``open_interest`` are already truncated to the
        evaluation timestamp (point-in-time); implementations must never
        shift with negative periods (lookahead).
        """
        ...


class FundingRateFeatures:
    """Compute funding-rate derived features (funding_rate_ma_3 etc.).

    Columns (as-is from ``quantflow.data.store`` meta parquet)::
        timestamp, funding_rate, realized_rate, funding_time
    """

    def compute(self, funding: pd.DataFrame) -> pd.DataFrame:
        if funding.empty:
            return pd.DataFrame()
        df = funding[["timestamp", "funding_rate"]].copy()
        df = df.sort_values("timestamp").reset_index(drop=True)
        df["funding_rate_ma_3"] = df["funding_rate"].rolling(3, min_periods=1).mean()
        df["funding_rate_abs_ma_3"] = df["funding_rate"].abs().rolling(3, min_periods=1).mean()
        # 8h skew: latest funding vs the 3-period mean (crowding signal).
        df["funding_skew_8h"] = df["funding_rate"] - df["funding_rate_ma_3"]
        return df


class OpenInterestFeatures:
    """Compute open-interest derived features (oi_change_1/3, oi_usd_ratio).

    Columns (as-is from ``quantflow.data.store`` meta parquet)::
        timestamp, open_interest, open_interest_ccy, open_interest_usd
    """

    def compute(self, oi: pd.DataFrame) -> pd.DataFrame:
        if oi.empty:
            return pd.DataFrame()
        df = oi[["timestamp", "open_interest", "open_interest_usd"]].copy()
        df = df.sort_values("timestamp").reset_index(drop=True)
        # pct_change(1/3) are causal (current vs past) — no future data.
        df["oi_change_1"] = df["open_interest"].pct_change(1)
        df["oi_change_3"] = df["open_interest"].pct_change(3)
        df["oi_usd_ratio"] = df["open_interest_usd"] / df["open_interest"].replace(0, pd.NA)
        return df


class MetaFeatureEngine:
    """Default L2 implementation of :class:`MetaFeatureComputer`.

    Aligns meta features to the OHLCV feature frame index (feature timestamps
    in ms), merging on the nearest past funding/OI record — the standard
    as-of join that keeps everything point-in-time.
    """

    def __init__(self) -> None:
        self._funding = FundingRateFeatures()
        self._oi = OpenInterestFeatures()

    def compute_meta_features(
        self,
        features: pd.DataFrame,
        funding: pd.DataFrame,
        open_interest: pd.DataFrame,
    ) -> pd.DataFrame:
        if features.empty:
            return features
        out = features.copy()
        if "timestamp" not in out.columns:
            logger.warning("MetaFeatureEngine: features frame lacks 'timestamp'; skip")
            return out

        fdf = self._funding.compute(funding)
        if not fdf.empty:
            out = _asof_merge(out, fdf, FUNDING_FEATURE_COLUMNS)

        oidf = self._oi.compute(open_interest)
        if not oidf.empty:
            out = _asof_merge(out, oidf, OI_FEATURE_COLUMNS)
        return out


def _asof_merge(
    features: pd.DataFrame,
    meta_df: pd.DataFrame,
    cols: tuple[str, ...],
) -> pd.DataFrame:
    """As-of join: nearest meta row at or before each feature timestamp."""
    out = features.copy()
    joined = pd.merge_asof(
        out.sort_values("timestamp").reset_index(drop=True),
        meta_df.sort_values("timestamp")[["timestamp", *cols]],
        on="timestamp",
        direction="backward",
        allow_exact_matches=True,
    )
    return joined[list(out.columns) + [c for c in cols if c not in out.columns]]
