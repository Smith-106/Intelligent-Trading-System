"""ZigZag pivot detector with multi-parameter consensus mechanism.

Implements ZigZagIndicator as a FactorBase factor, producing PivotSequence
with confidence-weighted pivot points. Multi-parameter consensus addresses
parameter sensitivity (Q1) with >80% overlap threshold (C-002).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

import numpy as np
import pandas as pd

from quantflow.indicators.base import FactorBase

logger = logging.getLogger(__name__)


class PivotDirection(IntEnum):
    HIGH = 1
    LOW = -1


@dataclass
class PivotPoint:
    """A single detected pivot point with confidence rating."""

    index: int
    price: float
    direction: PivotDirection
    confidence: float = 1.0  # 0.0-1.0, fraction of thresholds agreeing
    timestamp: int = 0  # UTC millisecond timestamp


@dataclass
class PivotSequence:
    """Sequence of consensus pivot points from multi-parameter ZigZag.

    W18a:
    - ``degraded`` is True when the low-consensus single-threshold fallback ran
      (ISS-20260613-007) — callers must treat this as lower confidence.
    - ``confirmed_pivots()`` drops the trailing in-progress extreme so PROGRESSIVE
      wave labels do not trade on a pivot that can still flip.
    """

    pivots: list[PivotPoint] = field(default_factory=list)
    overlap_ratio: float = 0.0  # average overlap across all pivots
    thresholds_used: list[float] = field(default_factory=list)
    degraded: bool = False  # True when low-consensus fallback was used
    consensus_n: int = 0  # number of threshold runs that produced pivots

    def confirmed_pivots(self) -> list[PivotPoint]:
        """Return pivots excluding the last (in-progress) extreme when present."""
        if len(self.pivots) <= 1:
            return list(self.pivots)
        return list(self.pivots[:-1])

    def with_confirmed_only(self) -> PivotSequence:
        """Copy of this sequence using only confirmed (non-final) pivots."""
        confirmed = self.confirmed_pivots()
        return PivotSequence(
            pivots=confirmed,
            overlap_ratio=self.overlap_ratio,
            thresholds_used=list(self.thresholds_used),
            degraded=self.degraded,
            consensus_n=self.consensus_n,
        )


class ZigZagIndicator(FactorBase):
    """Multi-parameter ZigZag pivot detector with consensus mechanism.

    Runs ZigZag detection at multiple threshold values and merges overlapping
    pivots into a consensus set. Pivots appear in consensus when >80% of
    parameter sets agree (configurable via min_overlap_ratio).
    """

    name = "zigzag_pivots"

    def compute(self, df: pd.DataFrame, **params: Any) -> pd.Series:
        """Compute ZigZag consensus pivots and return as a marker Series.

        The Series contains 1 for pivot highs, -1 for pivot lows, 0 otherwise.
        For full PivotSequence data, use compute_pivot_sequence() directly.
        """
        thresholds = params.get("thresholds", [0.03, 0.05, 0.08, 0.12, 0.15])
        min_overlap_ratio = params.get("min_overlap_ratio", 0.8)
        bar_tolerance = params.get("bar_tolerance", 3)

        seq = self.compute_pivot_sequence(
            df["high"],
            df["low"],
            df.get("timestamp", pd.Series(0, index=df.index)),
            thresholds=thresholds,
            min_overlap_ratio=min_overlap_ratio,
            bar_tolerance=bar_tolerance,
        )

        result = pd.Series(0, index=df.index, dtype=int)
        for p in seq.pivots:
            if p.index < len(result):
                result.iloc[p.index] = int(p.direction)
        return result

    def compute_pivot_sequence(
        self,
        high: pd.Series,
        low: pd.Series,
        timestamps: pd.Series,
        thresholds: list[float] | None = None,
        min_overlap_ratio: float = 0.8,
        bar_tolerance: int = 3,
    ) -> PivotSequence:
        """Run multi-parameter ZigZag and merge into consensus PivotSequence.

        Args:
            high: Series of high prices.
            low: Series of low prices.
            timestamps: Series of UTC timestamps (millisecond epoch).
            thresholds: ZigZag threshold values to run.
            min_overlap_ratio: Minimum ratio of thresholds agreeing (>0.8 per C-002).
            bar_tolerance: Max bar distance for merging pivots across runs.
        """
        if thresholds is None:
            thresholds = [0.03, 0.05, 0.08, 0.12, 0.15]
        min_overlap = max(1, int(len(thresholds) * min_overlap_ratio))

        all_pivots: list[tuple[float, pd.DataFrame]] = []
        for t in thresholds:
            p = _zigzag_single(high, low, threshold=t)
            if not p.empty:
                all_pivots.append((t, p))

        if not all_pivots:
            return PivotSequence(
                pivots=[],
                overlap_ratio=0.0,
                thresholds_used=thresholds,
                degraded=False,
                consensus_n=0,
            )

        merged = _merge_pivot_runs(
            [p for _, p in all_pivots], min_overlap=min_overlap, bar_tolerance=bar_tolerance
        )

        # ISS-20260613-007: low-volatility fallback — when min_overlap > 80%
        # produces no consensus pivots, fall back to the single ZigZag run whose
        # threshold is closest to the median of thresholds that produced results.
        # W18a: mark degraded=True so strategies can skip or flag (no silent trust).
        degraded = False
        if merged.empty:
            median_threshold = sorted(t for t, _ in all_pivots)[len(all_pivots) // 2]
            median_run = next(p for t, p in all_pivots if t == median_threshold)
            logger.warning(
                "Low consensus pivots, falling back to single-ZigZag result "
                "(threshold=%.4f, ISS-20260613-007, degraded=True)",
                median_threshold,
            )
            merged = median_run
            merged = merged.assign(overlap_count=1)
            degraded = True

        pivots_list: list[PivotPoint] = []
        for _, row in merged.iterrows():
            idx = int(row["pivot_idx"])
            ts = int(timestamps.iloc[idx]) if idx < len(timestamps) else 0
            pivots_list.append(
                PivotPoint(
                    index=idx,
                    price=float(row["pivot_price"]),
                    direction=PivotDirection(int(row["pivot_type"])),
                    confidence=float(row["overlap_count"]) / len(thresholds),
                    timestamp=ts,
                )
            )

        avg_overlap = sum(p.confidence for p in pivots_list) / max(1, len(pivots_list))

        return PivotSequence(
            pivots=pivots_list,
            overlap_ratio=avg_overlap,
            thresholds_used=thresholds,
            degraded=degraded,
            consensus_n=len(all_pivots),
        )


def _zigzag_single(
    high: pd.Series,
    low: pd.Series,
    threshold: float = 0.05,
) -> pd.DataFrame:
    """Single-threshold ZigZag pivot detection.

    Args:
        high: Series of high prices.
        low: Series of low prices.
        threshold: Minimum price move ratio (e.g. 0.05 = 5%).

    Returns:
        DataFrame with columns [pivot_idx, pivot_price, pivot_type].
    """
    n = len(high)
    if n < 3:
        return pd.DataFrame(columns=["pivot_idx", "pivot_price", "pivot_type"])

    pivots: list[dict[str, int | float]] = []
    direction = 0
    last_high_idx = 0
    last_low_idx = 0
    last_high = float(high.iloc[0])
    last_low = float(low.iloc[0])

    for i in range(1, n):
        h = float(high.iloc[i])
        low_price = float(low.iloc[i])

        if direction == 0:
            if h > last_high * (1 + threshold):
                direction = 1
                pivots.append(
                    {"pivot_idx": last_low_idx, "pivot_price": last_low, "pivot_type": -1}
                )
                last_high = h
                last_high_idx = i
            elif low_price < last_low * (1 - threshold):
                direction = -1
                pivots.append(
                    {"pivot_idx": last_high_idx, "pivot_price": last_high, "pivot_type": 1}
                )
                last_low = low_price
                last_low_idx = i
            else:
                if h > last_high:
                    last_high = h
                    last_high_idx = i
                if low_price < last_low:
                    last_low = low_price
                    last_low_idx = i
        elif direction == 1:
            if h > last_high:
                last_high = h
                last_high_idx = i
            elif low_price < last_high * (1 - threshold):
                direction = -1
                pivots.append(
                    {"pivot_idx": last_high_idx, "pivot_price": last_high, "pivot_type": 1}
                )
                last_low = low_price
                last_low_idx = i
        elif direction == -1:  # pragma: no cover - direction is always 0, 1, or -1 here
            if low_price < last_low:
                last_low = low_price
                last_low_idx = i
            elif h > last_low * (1 + threshold):
                direction = 1
                pivots.append(
                    {"pivot_idx": last_low_idx, "pivot_price": last_low, "pivot_type": -1}
                )
                last_high = h
                last_high_idx = i

    if direction == 1:
        pivots.append({"pivot_idx": last_high_idx, "pivot_price": last_high, "pivot_type": 1})
    elif direction == -1:
        pivots.append({"pivot_idx": last_low_idx, "pivot_price": last_low, "pivot_type": -1})

    return pd.DataFrame(pivots)


def _merge_pivot_runs(
    runs: list[pd.DataFrame],
    min_overlap: int = 4,
    bar_tolerance: int = 3,
) -> pd.DataFrame:
    """Merge multiple ZigZag runs into consensus pivots.

    Pivots from different runs that fall within bar_tolerance of each other
    and have the same direction are merged. Only pivots appearing in at
    least min_overlap runs are kept in the consensus set.
    """
    if not runs:
        return pd.DataFrame(columns=["pivot_idx", "pivot_price", "pivot_type", "overlap_count"])

    all_entries: list[dict[str, int | float]] = []
    for run_idx, run in enumerate(runs):
        for _, row in run.iterrows():
            all_entries.append(
                {
                    "run_idx": run_idx,
                    "pivot_idx": int(row["pivot_idx"]),
                    "pivot_price": float(row["pivot_price"]),
                    "pivot_type": int(row["pivot_type"]),
                }
            )

    if not all_entries:
        return pd.DataFrame(columns=["pivot_idx", "pivot_price", "pivot_type", "overlap_count"])

    entries_df = pd.DataFrame(all_entries)
    entries_df = entries_df.sort_values("pivot_idx").reset_index(drop=True)

    # Group nearby pivots with same direction
    groups: list[list[dict[str, int | float]]] = []
    current_group: list[dict[str, int | float]] = []

    for _, entry in entries_df.iterrows():
        if not current_group:
            current_group.append(
                {
                    "run_idx": int(entry["run_idx"]),
                    "pivot_idx": int(entry["pivot_idx"]),
                    "pivot_price": float(entry["pivot_price"]),
                    "pivot_type": int(entry["pivot_type"]),
                }
            )
            continue

        last = current_group[-1]
        idx_diff = abs(int(entry["pivot_idx"]) - int(last["pivot_idx"]))
        same_dir = int(entry["pivot_type"]) == int(last["pivot_type"])

        if idx_diff <= bar_tolerance and same_dir:
            current_group.append(
                {
                    "run_idx": int(entry["run_idx"]),
                    "pivot_idx": int(entry["pivot_idx"]),
                    "pivot_price": float(entry["pivot_price"]),
                    "pivot_type": int(entry["pivot_type"]),
                }
            )
        else:
            groups.append(current_group)
            current_group = [
                {
                    "run_idx": int(entry["run_idx"]),
                    "pivot_idx": int(entry["pivot_idx"]),
                    "pivot_price": float(entry["pivot_price"]),
                    "pivot_type": int(entry["pivot_type"]),
                }
            ]

    if current_group:  # pragma: no cover - all_entries creates the first group before this guard
        groups.append(current_group)

    # Merge groups into consensus pivots
    consensus: list[dict[str, int | float]] = []
    for group in groups:
        unique_runs = set(int(e["run_idx"]) for e in group)
        if len(unique_runs) >= min_overlap:
            avg_idx = int(np.mean([int(e["pivot_idx"]) for e in group]))
            avg_price = float(np.mean([float(e["pivot_price"]) for e in group]))
            pivot_type = int(group[0]["pivot_type"])
            consensus.append(
                {
                    "pivot_idx": avg_idx,
                    "pivot_price": avg_price,
                    "pivot_type": pivot_type,
                    "overlap_count": len(unique_runs),
                }
            )

    if not consensus:
        return pd.DataFrame(columns=["pivot_idx", "pivot_price", "pivot_type", "overlap_count"])

    return pd.DataFrame(consensus).sort_values("pivot_idx").reset_index(drop=True)
