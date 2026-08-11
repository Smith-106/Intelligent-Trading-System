"""Honest search-budget accounting for DSR n_trials.

Prevents under-reporting trials (DSR wash). Research OS only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TrialsBreakdown:
    """Search budget components (all non-negative ints)."""

    barrier_grid: int = 0
    optimize_trials: int = 0
    cpcv_paths: int = 0
    wfo_windows: int = 0
    manual_sweeps: int = 0
    other: int = 0

    def total(self) -> int:
        return (
            int(self.barrier_grid)
            + int(self.optimize_trials)
            + int(self.cpcv_paths)
            + int(self.wfo_windows)
            + int(self.manual_sweeps)
            + int(self.other)
        )

    def to_dict(self) -> dict[str, int]:
        d = asdict(self)
        return {k: int(v) for k, v in d.items()}


@dataclass
class TrialsAccount:
    n_trials_accounted: int
    breakdown: dict[str, int]
    underreported: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_trials_accounted": self.n_trials_accounted,
            "n_trials_breakdown": self.breakdown,
            "underreported": self.underreported,
            "notes": list(self.notes),
        }


def account_n_trials(breakdown: TrialsBreakdown | dict[str, int]) -> TrialsAccount:
    """Sum breakdown into n_trials_accounted (minimum 1 if any search occurred)."""
    if isinstance(breakdown, TrialsBreakdown):
        bd = breakdown
    else:
        bd = TrialsBreakdown(
            barrier_grid=int(breakdown.get("barrier_grid", 0)),
            optimize_trials=int(breakdown.get("optimize_trials", 0)),
            cpcv_paths=int(breakdown.get("cpcv_paths", 0)),
            wfo_windows=int(breakdown.get("wfo_windows", 0)),
            manual_sweeps=int(breakdown.get("manual_sweeps", 0)),
            other=int(breakdown.get("other", 0)),
        )
    for name, val in bd.to_dict().items():
        if val < 0:
            raise ValueError(f"breakdown.{name} must be >= 0, got {val}")
    total = bd.total()
    notes: list[str] = []
    if total == 0:
        notes.append("zero search budget — use n_trials_accounted=1 for single fixed config")
        total = 1
    return TrialsAccount(
        n_trials_accounted=total,
        breakdown=bd.to_dict(),
        underreported=False,
        notes=notes,
    )


def assert_honest_n_trials(
    n_trials_accounted: int,
    breakdown: TrialsBreakdown | dict[str, int],
) -> TrialsAccount:
    """Fail if claimed n_trials is less than sum(breakdown)."""
    acc = account_n_trials(breakdown)
    claimed = int(n_trials_accounted)
    if claimed < acc.n_trials_accounted:
        acc.underreported = True
        acc.notes.append(
            f"underreported: claimed n_trials={claimed} < sum(breakdown)={acc.n_trials_accounted}"
        )
        # keep accounted as the honest floor
        return acc
    # If caller claims more, accept higher (conservative for DSR)
    if claimed > acc.n_trials_accounted:
        acc.n_trials_accounted = claimed
        acc.notes.append("claimed n_trials exceeds breakdown sum — using claimed (conservative)")
    return acc


def grid_size(param_space: dict[str, tuple[Any, ...] | list[Any]]) -> int:
    """Cartesian product size of discrete param space."""
    if not param_space:
        return 0
    n = 1
    for _k, vals in param_space.items():
        m = len(tuple(vals))
        if m == 0:
            return 0
        n *= m
    return n
