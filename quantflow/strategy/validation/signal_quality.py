"""Signal quality metrics for out-of-sample validation."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def signal_quality_metrics(
    close: pd.Series,
    entries: pd.Series,
    exits: pd.Series | None = None,
    probabilities: pd.Series | None = None,
    oos_sharpe: float | None = None,
) -> dict[str, Any]:
    """Evaluate directional signal quality against next-bar returns.

    The metrics are intentionally simple and point-in-time: a bar with an
    entry signal is treated as a positive prediction for the next close-to-close
    return. This gives validation and ML training a shared, leak-resistant
    quality vocabulary without importing higher layers.
    """
    del exits
    aligned_entries = entries.reindex(close.index).fillna(False).astype(bool)
    forward_returns = close.pct_change().shift(-1)
    labels = (forward_returns > 0).astype(int)
    valid = forward_returns.notna()

    if not valid.any():
        return {
            "precision": 0.0,
            "recall": 0.0,
            "hit_rate": 0.0,
            "brier_score": 0.0,
            "oos_sharpe": float(oos_sharpe or 0.0),
            "n_predictions": 0,
            "n_signals": 0,
        }

    y_true = labels.loc[valid].astype(int)
    y_pred = aligned_entries.loc[valid].astype(int)

    tp = int(((y_pred == 1) & (y_true == 1)).sum())
    fp = int(((y_pred == 1) & (y_true == 0)).sum())
    fn = int(((y_pred == 0) & (y_true == 1)).sum())

    n_signals = int(y_pred.sum())
    precision = tp / (tp + fp) if tp + fp > 0 else 0.0
    recall = tp / (tp + fn) if tp + fn > 0 else 0.0
    hit_rate = precision if n_signals > 0 else 0.0

    if probabilities is None:
        proba = y_pred.astype(float)
    else:
        proba = probabilities.reindex(y_true.index).fillna(0.5).clip(0.0, 1.0)
    brier = float(np.mean((proba.to_numpy(dtype=float) - y_true.to_numpy(dtype=float)) ** 2))

    return {
        "precision": float(precision),
        "recall": float(recall),
        "hit_rate": float(hit_rate),
        "brier_score": brier,
        "oos_sharpe": float(oos_sharpe or 0.0),
        "n_predictions": len(y_true),
        "n_signals": n_signals,
    }


def aggregate_signal_quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-window signal quality dictionaries."""
    if not rows:
        return {
            "precision": 0.0,
            "recall": 0.0,
            "hit_rate": 0.0,
            "brier_score": 0.0,
            "oos_sharpe": 0.0,
            "n_predictions": 0,
            "n_signals": 0,
        }

    total_predictions = sum(int(row.get("n_predictions", 0)) for row in rows)
    total_signals = sum(int(row.get("n_signals", 0)) for row in rows)

    def _weighted(metric: str) -> float:
        if total_predictions <= 0:
            return 0.0
        return float(
            sum(float(row.get(metric, 0.0)) * int(row.get("n_predictions", 0)) for row in rows)
            / total_predictions
        )

    return {
        "precision": _weighted("precision"),
        "recall": _weighted("recall"),
        "hit_rate": _weighted("hit_rate"),
        "brier_score": _weighted("brier_score"),
        "oos_sharpe": _weighted("oos_sharpe"),
        "n_predictions": total_predictions,
        "n_signals": total_signals,
    }
