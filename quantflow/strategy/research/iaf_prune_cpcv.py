"""IAF correlation prune → CPCV research pipeline (never hard-bind entry).

Pipeline:
1. Compute IAF factor frame
2. ``prune_correlated_factors`` (research-only)
3. Build a **lagged** research signal from kept factors (majority z-score)
4. Run CPCV on that signal with honest n_trials
5. Always set ``hard_bind_entry=False`` and ``promotion_eligible=False``
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from quantflow.strategy.research.iaf_prune import (
    IAF_FACTOR_NAMES,
    PruneConfig,
    prune_correlated_factors,
)
from quantflow.strategy.research.n_trials_budget import TrialsBreakdown, account_n_trials
from quantflow.strategy.validation.cpcv import cpcv_backtest


def _compute_iaf_frame(df: pd.DataFrame) -> pd.DataFrame:
    from quantflow.indicators.engine import IndicatorEngine

    eng = IndicatorEngine()
    factors = eng.batch_calculate(df)
    cols = [c for c in IAF_FACTOR_NAMES if c in factors.columns]
    if not cols:
        # engine may return full frame; try intersect
        cols = [c for c in factors.columns if c in IAF_FACTOR_NAMES]
    if not cols:
        raise ValueError("no IAF factor columns available (fail-closed)")
    return factors[cols].copy()


def research_signal_from_kept_factors(
    factor_frame: pd.DataFrame,
    kept: list[str],
    *,
    lag: int = 1,
) -> tuple[pd.Series, pd.Series]:
    """Lagged majority z-score long/flat signal (research only).

    Causal: factors are shifted by ``lag`` (>=1) before decision.
    """
    if lag < 1:
        raise ValueError("lag must be >= 1 (no look-ahead)")
    if not kept:
        raise ValueError("kept factors empty (fail-closed)")
    use = [c for c in kept if c in factor_frame.columns]
    if not use:
        raise ValueError("kept factors not present in frame")

    z = factor_frame[use].astype(float)
    # rolling z-score per column (expanding-safe: use rolling 100)
    mu = z.rolling(100, min_periods=30).mean()
    sd = z.rolling(100, min_periods=30).std().replace(0.0, np.nan)
    zz = (z - mu) / sd
    score = zz.mean(axis=1)
    # lag decision
    score_lag = score.shift(lag)
    long = (score_lag > 0).fillna(False).astype(bool)
    # entries: transition to long; exits: transition to flat
    prev = long.shift(1).fillna(False).astype(bool)
    entries = long & ~prev
    exits = (~long) & prev
    return entries.astype(bool), exits.astype(bool)


def run_iaf_prune_cpcv(
    df: pd.DataFrame,
    *,
    threshold: float = 0.7,
    method: str = "spearman",
    cpcv_groups: int = 6,
    cpcv_test_groups: int = 2,
    fee: float = 0.001,
    lag: int = 1,
) -> dict[str, Any]:
    """Prune IAF factors then CPCV the research signal — never bind entry."""
    if df is None or df.empty or "close" not in df.columns:
        raise ValueError("df with close required (fail-closed)")

    frame = _compute_iaf_frame(df)
    prune = prune_correlated_factors(
        frame,
        columns=list(frame.columns),
        config=PruneConfig(threshold=threshold, method=method),
    )
    entries, exits = research_signal_from_kept_factors(frame, prune.kept, lag=lag)
    # align to close index
    close = df["close"].astype(float)
    if len(entries) != len(close):
        # reindex if factor engine used different index
        entries = entries.reindex(close.index).fillna(False).astype(bool)
        exits = exits.reindex(close.index).fillna(False).astype(bool)
        if len(entries) != len(
            close
        ):  # pragma: no cover - reindex always equalizes length to close.index
            # positional fallback
            n = min(len(entries), len(close))
            entries = pd.Series(entries.to_numpy()[:n], index=close.index[:n])
            exits = pd.Series(exits.to_numpy()[:n], index=close.index[:n])
            close = close.iloc[:n]

    from math import comb

    cpcv_paths = comb(cpcv_groups, cpcv_test_groups) if cpcv_groups >= cpcv_test_groups else 0
    # Fixed research signal — no param grid search inside CPCV
    breakdown = TrialsBreakdown(
        barrier_grid=0,
        optimize_trials=0,
        cpcv_paths=int(cpcv_paths),
        wfo_windows=0,
        manual_sweeps=1,  # one prune config / threshold choice
        other=0,
    )
    acc = account_n_trials(breakdown)

    cpcv = cpcv_backtest(
        close,
        entries,
        exits,
        n_groups=cpcv_groups,
        n_test_groups=cpcv_test_groups,
        fee=fee,
        # fixed signal — no signal_fn/param_space optimize
    )
    pbo = float(cpcv.get("pbo", 1.0) or 1.0)
    cpcv_pass = bool(cpcv.get("passed", pbo < 0.5))

    return {
        "promotion_eligible": False,
        "hard_bind_entry": False,
        "research_only": True,
        "note": (
            "IAF prune→CPCV is research evidence only; "
            "do NOT hard-bind kept factors into live/paper entry defaults or freeze contracts"
        ),
        "prune": prune.to_dict(),
        "signal": {
            "type": "lagged_majority_zscore",
            "lag": lag,
            "kept": list(prune.kept),
            "n_entries": int(entries.sum()),
            "n_exits": int(exits.sum()),
        },
        "n_trials_accounted": acc.n_trials_accounted,
        "n_trials_breakdown": acc.breakdown,
        "underreported": acc.underreported,
        "cpcv": {
            "passed": cpcv_pass,
            "pbo": pbo,
            "decision": "PASS" if cpcv_pass else "NO-GO",
            "raw": {
                k: cpcv.get(k)
                for k in (
                    "pbo",
                    "passed",
                    "n_paths",
                    "mean_oos_sharpe",
                    "mean_is_sharpe",
                    "optimized",
                )
                if k in cpcv
            },
        },
        "research_go": "GO_DISCUSS" if cpcv_pass and not acc.underreported else "NO-GO",
    }
