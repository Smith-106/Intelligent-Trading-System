"""IAF factor correlation prune — research filter only.

Does NOT bind factors into live/paper entry defaults or freeze contracts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

# IAF pack names (must stay in sync with engine.CLASSICAL_EXTENDED IAF block)
IAF_FACTOR_NAMES: tuple[str, ...] = (
    "cci_20",
    "roc_12",
    "mom_10",
    "aroon_up",
    "aroon_down",
    "aroon_osc",
    "cmf_20",
    "realized_vol_20",
    "bb_width_20",
    "percent_b_20",
    "trix_15",
    "tsi",
)


@dataclass(frozen=True)
class PruneConfig:
    """Correlation prune settings."""

    threshold: float = 0.7
    method: str = "spearman"  # spearman | pearson
    min_periods: int = 30
    prefer: tuple[str, ...] = ()  # optional priority keep order


@dataclass
class PruneResult:
    kept: list[str]
    dropped: list[str]
    threshold: float
    method: str
    pairwise_dropped: list[dict[str, Any]] = field(default_factory=list)
    research_only: bool = True
    note: str = "IAF prune is research-only; do not hard-bind into live entry or freeze contracts"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def prune_correlated_factors(
    frame: pd.DataFrame,
    *,
    columns: list[str] | tuple[str, ...] | None = None,
    config: PruneConfig | None = None,
) -> PruneResult:
    """Greedy correlation prune: drop later cols with |corr| > threshold vs kept.

    Empty input / no usable columns raises ValueError (fail-closed).
    """
    cfg = config or PruneConfig()
    if frame is None or frame.empty:
        raise ValueError("factor frame is empty (fail-closed)")
    cols = (
        list(columns)
        if columns is not None
        else [c for c in IAF_FACTOR_NAMES if c in frame.columns]
    )
    if not cols:
        # fall back to all numeric columns
        cols = [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])]
    if not cols:
        raise ValueError("no factor columns to prune (fail-closed)")

    # priority: prefer list first, then given order
    ordered: list[str] = []
    for name in cfg.prefer:
        if name in cols and name not in ordered:
            ordered.append(name)
    for name in cols:
        if name not in ordered:
            ordered.append(name)

    sub = frame[ordered].apply(pd.to_numeric, errors="coerce")
    if cfg.method == "spearman":
        corr = sub.corr(method="spearman", min_periods=cfg.min_periods)
    elif cfg.method == "pearson":
        corr = sub.corr(method="pearson", min_periods=cfg.min_periods)
    else:
        raise ValueError(f"unknown correlation method {cfg.method!r}")

    kept: list[str] = []
    dropped: list[str] = []
    pairwise: list[dict[str, Any]] = []
    thr = float(cfg.threshold)

    for col in ordered:
        if col not in corr.columns:
            dropped.append(col)
            continue
        drop_me = False
        for k in kept:
            rho = corr.loc[col, k]
            if rho is None or (isinstance(rho, float) and np.isnan(rho)):
                continue
            if abs(float(rho)) > thr:
                drop_me = True
                pairwise.append(
                    {
                        "dropped": col,
                        "kept_conflict": k,
                        "abs_corr": round(abs(float(rho)), 6),
                    }
                )
                break
        if drop_me:
            dropped.append(col)
        else:
            kept.append(col)

    return PruneResult(
        kept=kept,
        dropped=dropped,
        threshold=thr,
        method=cfg.method,
        pairwise_dropped=pairwise,
    )


def prune_report_to_dict(result: PruneResult) -> dict[str, Any]:
    return result.to_dict()
