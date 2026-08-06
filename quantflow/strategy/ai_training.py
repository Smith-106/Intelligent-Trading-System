"""AI model training pipeline — features → labels → model → validation report.

s3-ai-research-pipeline (wave2, T-s3-03): orchestrates the ML model
training loop and produces a validation report consumable by
:class:`quantflow.strategy.model_registry.ModelRegistry`. The report's
``decision`` field is the GO/NO-GO output of the existing
``validation.gate.validation_gate`` — the registry refuses to register
anything that did not pass the gate (fail-closed).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class TrainedModelReport:
    """Outcome of training + validation for one model candidate."""

    model_id: str
    model_cls: str
    features_hash: str
    n_samples: int
    validation: dict[str, Any] = field(default_factory=dict)
    feature_importance: dict[str, float] = field(default_factory=dict)
    decision: str = "NO-GO"  # GO | NO-GO (from validation_gate)
    reason: str = "not validated"
    trained_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_cls": self.model_cls,
            "features_hash": self.features_hash,
            "n_samples": self.n_samples,
            "validation": self.validation,
            "feature_importance": self.feature_importance,
            "decision": self.decision,
            "reason": self.reason,
            "trained_at": self.trained_at,
        }


def _features_hash(features: pd.DataFrame) -> str:
    """Stable hash of feature matrix shape + column names (not values)."""
    import hashlib

    blob = f"{features.shape}|{','.join(features.columns)}".encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def _signals_from_probability(
    proba: pd.Series,
    threshold: float = 0.5,
    direction: int = 1,
) -> pd.Series:
    """Turn P(up) into directional signals: +1 long / 0 flat / -1 short."""
    out = pd.Series(0, index=proba.index, dtype=int)
    out[proba >= threshold] = direction
    out[proba <= 1 - threshold] = -direction
    return out


class AITrainingPipeline:
    """Train an ML classifier and validate it via the standard gate.

    The pipeline is deliberately model-agnostic (any sklearn-style
    classifier with ``fit`` / ``predict_proba`` works). Signals are derived
    from predicted probabilities and validated with CPCV/DSR/WFO through
    ``validation_gate`` — the same gate strategies must pass.
    """

    def __init__(
        self,
        forecast_horizon: int = 5,
        test_size: float = 0.3,
        random_state: int = 42,
        validation_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.forecast_horizon = forecast_horizon
        self.test_size = test_size
        self.random_state = random_state
        #: Extra kwargs forwarded to validation_gate (e.g. cpcv_groups,
        #: wfo_windows, n_trials) — tests shrink them for speed.
        self.validation_kwargs = validation_kwargs or {}

    def train(
        self,
        features: pd.DataFrame,
        close: pd.Series,
        model_cls: Any,
        **model_kwargs: Any,
    ) -> TrainedModelReport:
        """Train + validate.

        Args:
            features: Feature matrix indexed like ``close`` (must contain
                ``timestamp`` for alignment when index is not datetime).
            close: Close-price series (index aligned to features).
            model_cls: sklearn-style classifier class.
            **model_kwargs: kwargs for the classifier constructor.

        Returns:
            TrainedModelReport with ``decision`` GO/NO-GO.
        """
        from sklearn.ensemble import RandomForestClassifier

        model_cls = model_cls or RandomForestClassifier
        model = model_cls(random_state=self.random_state, **model_kwargs)

        # Label: forward return > 0 → 1 (time-point safe: shift(-h) is the
        # label definition, never a feature). If the feature frame already
        # contains a 'close' column, drop it — close is the label source only.
        train_features = features.drop(columns=["close"], errors="ignore")
        aligned = pd.concat(
            [train_features, close.rename("close")],
            axis=1,
            join="inner",
        ).dropna()
        if len(aligned) < 60:
            logger.warning("AITrainingPipeline: insufficient rows (%d)", len(aligned))
            return TrainedModelReport(
                model_id="",
                model_cls=model_cls.__name__,
                features_hash=_features_hash(features),
                n_samples=len(aligned),
                decision="NO-GO",
                reason="insufficient samples (< 60)",
            )

        # Chronological split (never shuffle — time series).
        split = int(len(aligned) * (1 - self.test_size))
        feature_cols = [c for c in aligned.columns if c != "close"]
        X = aligned[feature_cols].values
        y = (
            aligned["close"]
            .pct_change(self.forecast_horizon)
            .shift(-self.forecast_horizon)
            .gt(0)
            .astype(int)
            .values
        )
        y = np.where(np.isnan(y), 0, y).astype(int)
        model.fit(X[:split], y[:split])

        # Out-of-sample probability + signals on the full aligned frame.
        proba_matrix = np.asarray(model.predict_proba(X), dtype=float)
        proba = proba_matrix[:, 1] if proba_matrix.shape[1] > 1 else np.ones(len(X))
        proba_series = pd.Series(proba, index=aligned.index)
        signals = _signals_from_probability(proba_series)

        # Build entries/exits for the validation gate.
        entries = pd.Series(0, index=aligned.index, dtype=int)
        exits = pd.Series(0, index=aligned.index, dtype=int)
        entries[(signals == 1) & (signals.shift(1, fill_value=0) != 1)] = 1
        entries[(signals == -1) & (signals.shift(1, fill_value=0) != -1)] = -1
        exits[(signals == 0) & (signals.shift(1, fill_value=0) != 0)] = 1

        from quantflow.strategy.validation.gate import validation_gate

        gate_result = validation_gate(
            close=aligned["close"],
            entries=entries,
            exits=exits,
            **self.validation_kwargs,
        )

        importance: dict[str, float] = {}
        if hasattr(model, "feature_importances_"):
            importances = np.asarray(model.feature_importances_, dtype=float)
            importance = dict(
                sorted(
                    zip(feature_cols, importances, strict=True),
                    key=lambda kv: kv[1],
                    reverse=True,
                )[:10]
            )

        return TrainedModelReport(
            model_id="",
            model_cls=model_cls.__name__,
            features_hash=_features_hash(features),
            n_samples=len(aligned),
            validation=gate_result,
            feature_importance=importance,
            decision=str(gate_result.get("decision", "NO-GO")),
            reason=str(gate_result.get("reason", "gate ran")),
        )
