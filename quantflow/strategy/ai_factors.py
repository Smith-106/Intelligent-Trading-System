"""AI-powered factor generation engine.

Provides Meta-Labeling (secondary model filtering), feature importance
via tree-based models, and an extensible interface for custom ML factors.
Qlib-style RD-Agent integration is via the CLI research workflow.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class MetaLabelResult:
    """Result from Meta-Labeling binary classification."""

    predictions: pd.Series
    probability: pd.Series
    precision: float
    recall: float
    accuracy: float
    feature_importance: dict[str, float] = field(default_factory=dict)


class AIFactorEngine:
    """Generate AI-augmented factors and meta-labels.

    Meta-Labeling workflow:
    1. Primary model: simple rule-based signals (from strategy)
    2. Secondary model: ML classifier filters false positives
    3. Only trade when both primary AND secondary agree

    This reduces false signals while preserving the strategy's edge.
    """

    def __init__(self, model_type: str = "random_forest", random_state: int = 42):
        self.model_type = model_type
        self.random_state = random_state
        self._model: Any = None
        self._feature_names: list[str] = []

    def meta_label(
        self,
        features: pd.DataFrame,
        primary_signals: pd.Series,
        forward_returns: pd.Series,
        threshold: float = 0.0,
        test_size: float = 0.3,
    ) -> MetaLabelResult:
        """Apply Meta-Labeling to filter primary signals.

        Args:
            features: Feature matrix (indicators, macro, etc.).
            primary_signals: Primary model signals (1=long, -1=short, 0=flat).
            forward_returns: Forward period returns for labeling.
            threshold: Minimum return to consider as positive label.
            test_size: Fraction of data for out-of-sample evaluation.

        Returns:
            MetaLabelResult with predictions and performance metrics.
        """
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import accuracy_score, precision_score, recall_score

        # Create binary labels: 1 if primary signal was correct, 0 otherwise
        correct = pd.Series(0, index=features.index, dtype=int)
        long_mask = primary_signals == 1
        short_mask = primary_signals == -1
        correct[long_mask] = (forward_returns[long_mask] > threshold).astype(int)
        correct[short_mask] = (forward_returns[short_mask] < -threshold).astype(int)

        # Align indices
        valid_idx = features.dropna().index.intersection(correct.index)
        X = features.loc[valid_idx].values
        y = correct.loc[valid_idx].values

        if len(X) < 50:
            logger.warning("Insufficient data for meta-labeling: %d rows", len(X))
            return MetaLabelResult(
                predictions=pd.Series(0, index=features.index),
                probability=pd.Series(0.5, index=features.index),
                precision=0.0,
                recall=0.0,
                accuracy=0.0,
            )

        # Train/test split (chronological)
        split_idx = int(len(X) * (1 - test_size))
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]

        # Train secondary model
        self._model = RandomForestClassifier(
            n_estimators=100,
            max_depth=5,
            random_state=self.random_state,
            class_weight="balanced",
        )
        self._model.fit(X_train, y_train)
        self._feature_names = list(features.columns)

        # Evaluate
        y_pred = self._model.predict(X_test)

        # Full predictions for all data
        all_pred = self._model.predict(X)
        all_prob = (
            self._model.predict_proba(X)[:, 1] if len(self._model.classes_) > 1 else np.ones(len(X))
        )

        predictions = pd.Series(0, index=features.index, dtype=int)
        probability = pd.Series(0.5, index=features.index)
        predictions.loc[valid_idx] = all_pred
        probability.loc[valid_idx] = all_prob

        # Feature importance
        importance = dict(zip(self._feature_names, self._model.feature_importances_, strict=True))
        top_importance = dict(sorted(importance.items(), key=lambda x: x[1], reverse=True)[:10])

        return MetaLabelResult(
            predictions=predictions,
            probability=probability,
            precision=float(precision_score(y_test, y_pred, zero_division=0)),
            recall=float(recall_score(y_test, y_pred, zero_division=0)),
            accuracy=float(accuracy_score(y_test, y_pred)),
            feature_importance=top_importance,
        )

    def compute_factor(
        self,
        features: pd.DataFrame,
        forward_returns: pd.Series,
        lookahead: int = 1,
    ) -> pd.Series:
        """Compute AI factor: probability of positive forward return.

        Uses a simple gradient-boosted classifier to predict the direction
        of future returns from the feature set.

        Args:
            features: Feature matrix.
            forward_returns: Forward returns for labeling.
            lookahead: Number of bars to look ahead.

        Returns:
            Series of probabilities [0, 1] for positive return.
        """
        from sklearn.ensemble import GradientBoostingClassifier

        valid_idx = features.dropna().index.intersection(forward_returns.dropna().index)
        X = features.loc[valid_idx].values
        y = (forward_returns.loc[valid_idx] > 0).astype(int).values

        if len(X) < 50:
            return pd.Series(0.5, index=features.index)

        model = GradientBoostingClassifier(
            n_estimators=50,
            max_depth=3,
            random_state=self.random_state,
        )
        model.fit(X, y)
        prob = model.predict_proba(X)[:, 1] if len(model.classes_) > 1 else np.ones(len(X))

        result = pd.Series(0.5, index=features.index)
        result.loc[valid_idx] = prob
        return result

    def feature_selection(
        self,
        features: pd.DataFrame,
        target: pd.Series,
        n_top: int = 10,
    ) -> list[str]:
        """Select top features by importance using mutual information.

        Args:
            features: Feature matrix.
            target: Target variable.
            n_top: Number of features to select.

        Returns:
            List of selected feature names, sorted by importance.
        """
        from sklearn.feature_selection import mutual_info_classif

        valid_idx = features.dropna().index.intersection(target.dropna().index)
        X = features.loc[valid_idx].values
        y = target.loc[valid_idx].values

        if len(X) < 30:
            return list(features.columns[:n_top])

        mi = mutual_info_classif(X, y, random_state=self.random_state)
        importance = dict(zip(features.columns, mi, strict=True))
        sorted_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)
        return [f[0] for f in sorted_features[:n_top]]
