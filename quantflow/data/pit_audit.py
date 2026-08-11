"""Point-in-time (PIT) audit helpers for Feature Store (IMP-03).

Scope:
  - OHLCV raw bars fed into indicator compute must not exceed cutoff
  - Saved/loaded feature rows must not exceed ``end``
  - Optional funding/OI meta as-of max timestamp must not exceed cutoff

Does not rewrite storage. Fail-closed: any future row → audit failed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from quantflow.data.feature_store import FeatureStore
from quantflow.data.store import DataStore


class PITAuditError(ValueError):
    """Raised when a fail-closed PIT audit detects lookahead."""


@dataclass
class PITAuditResult:
    """Structured audit outcome."""

    passed: bool
    scope: str
    cutoff_ms: int | None = None
    reasons: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def raise_if_failed(self) -> None:
        if not self.passed:
            msg = "; ".join(self.reasons) or "PIT audit failed"
            raise PITAuditError(msg)


def max_timestamp_ms(df: pd.DataFrame, column: str = "timestamp") -> int | None:
    """Return max timestamp as int ms, or None if empty/missing."""
    if df is None or df.empty or column not in df.columns:
        return None
    series = df[column]
    try:
        return int(series.astype("int64").max())
    except (TypeError, ValueError):
        return int(pd.to_datetime(series, utc=True).astype("int64").max() // 1_000_000)


def audit_frame_no_future(
    df: pd.DataFrame,
    *,
    cutoff_ms: int,
    column: str = "timestamp",
    scope: str = "frame",
) -> PITAuditResult:
    """Assert no row has ``timestamp > cutoff_ms``."""
    reasons: list[str] = []
    details: dict[str, Any] = {
        "n_rows": 0 if df is None or df.empty else len(df),
        "cutoff_ms": int(cutoff_ms),
    }
    if df is None or df.empty:
        return PITAuditResult(
            passed=True,
            scope=scope,
            cutoff_ms=int(cutoff_ms),
            reasons=[],
            details={**details, "empty": True},
        )
    if column not in df.columns:
        reasons.append(f"missing timestamp column {column!r}")
        return PITAuditResult(
            passed=False,
            scope=scope,
            cutoff_ms=int(cutoff_ms),
            reasons=reasons,
            details=details,
        )
    max_ts = max_timestamp_ms(df, column)
    details["max_timestamp_ms"] = max_ts
    if max_ts is not None and max_ts > int(cutoff_ms):
        n_future = int((df[column].astype("int64") > int(cutoff_ms)).sum())
        reasons.append(
            f"{scope}: {n_future} row(s) with {column}>{cutoff_ms} "
            f"(max={max_ts}) — lookahead"
        )
        details["n_future"] = n_future
    return PITAuditResult(
        passed=len(reasons) == 0,
        scope=scope,
        cutoff_ms=int(cutoff_ms),
        reasons=reasons,
        details=details,
    )


def audit_compute_features_pit(
    feature_store: FeatureStore,
    *,
    symbol: str,
    cutoff_ms: int,
    indicator_names: list[str] | None = None,
    raw_store: DataStore,
    meta_store: Any | None = None,
) -> PITAuditResult:
    """Run FeatureStore.compute_features and audit raw+output timestamps."""
    reasons: list[str] = []
    details: dict[str, Any] = {"symbol": symbol, "cutoff_ms": int(cutoff_ms)}

    # Probe raw query independently (same end=cutoff contract)
    raw = raw_store.query(symbol, end=cutoff_ms)
    raw_audit = audit_frame_no_future(
        raw, cutoff_ms=cutoff_ms, scope="raw_ohlcv"
    )
    details["raw"] = raw_audit.details
    if not raw_audit.passed:
        reasons.extend(raw_audit.reasons)

    features = feature_store.compute_features(
        symbol,
        cutoff_ms,
        indicator_names or [],
        raw_store=raw_store,
        meta_store=meta_store,
    )
    feat_audit = audit_frame_no_future(
        features, cutoff_ms=cutoff_ms, scope="features_output"
    )
    details["features"] = feat_audit.details
    if not feat_audit.passed:
        reasons.extend(feat_audit.reasons)

    # computed_at must equal cutoff when present
    if features is not None and not features.empty and "computed_at" in features.columns:
        bad = features[features["computed_at"].astype("int64") != int(cutoff_ms)]
        if not bad.empty:
            reasons.append(
                f"features_output: {len(bad)} row(s) computed_at != cutoff {cutoff_ms}"
            )
            details["bad_computed_at"] = len(bad)

    # meta columns if present
    if features is not None and not features.empty:
        for col in ("meta_max_funding_ts", "meta_max_oi_ts"):
            if col in features.columns:
                vals = features[col].dropna()
                if not vals.empty:
                    mx = int(vals.astype("int64").max())
                    details[col] = mx
                    if mx > int(cutoff_ms) and mx >= 0:
                        reasons.append(
                            f"meta as-of {col}={mx} exceeds cutoff {cutoff_ms}"
                        )

    return PITAuditResult(
        passed=len(reasons) == 0,
        scope="compute_features",
        cutoff_ms=int(cutoff_ms),
        reasons=reasons,
        details=details,
    )


def audit_load_features_pit(
    feature_store: FeatureStore,
    *,
    symbol: str,
    end_ms: int,
    start_ms: int | None = None,
) -> PITAuditResult:
    """Load features with end cutoff and ensure no future rows."""
    loaded = feature_store.load_features(symbol, start=start_ms, end=end_ms)
    result = audit_frame_no_future(
        loaded, cutoff_ms=end_ms, scope="load_features"
    )
    result.details["symbol"] = symbol
    result.details["start_ms"] = start_ms
    return result


def run_pit_audit_suite(
    feature_store: FeatureStore,
    *,
    symbol: str,
    cutoff_ms: int,
    raw_store: DataStore,
    indicator_names: list[str] | None = None,
    meta_store: Any | None = None,
    also_load: bool = True,
) -> PITAuditResult:
    """Aggregate compute (+ optional load) audits into one result."""
    reasons: list[str] = []
    details: dict[str, Any] = {}
    compute = audit_compute_features_pit(
        feature_store,
        symbol=symbol,
        cutoff_ms=cutoff_ms,
        indicator_names=indicator_names,
        raw_store=raw_store,
        meta_store=meta_store,
    )
    details["compute"] = compute.to_dict()
    if not compute.passed:
        reasons.extend(compute.reasons)

    if also_load:
        load = audit_load_features_pit(
            feature_store, symbol=symbol, end_ms=cutoff_ms
        )
        details["load"] = load.to_dict()
        if not load.passed:
            reasons.extend(load.reasons)

    return PITAuditResult(
        passed=len(reasons) == 0,
        scope="pit_audit_suite",
        cutoff_ms=int(cutoff_ms),
        reasons=reasons,
        details=details,
    )


def intentional_leak_frame(
    stamps: list[int],
    *,
    cutoff_ms: int,
) -> pd.DataFrame:
    """Build a frame that *includes* a future bar (for negative tests)."""
    future = int(cutoff_ms) + 3_600_000
    all_ts = [*list(stamps), future]
    return pd.DataFrame(
        {
            "timestamp": all_ts,
            "close": [100.0 + i for i in range(len(all_ts))],
        }
    )
