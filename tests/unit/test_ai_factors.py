"""Tests for ai_factors module — with mock for sklearn."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.ai_factors import AIFactorEngine, MetaLabelResult


class TestAIFactorEngine:
    """Test AIFactorEngine meta-labeling and factor computation."""

    @pytest.fixture
    def sample_data(self):
        np.random.seed(42)
        n = 200
        features = pd.DataFrame(
            {
                "rsi": np.random.randn(n).cumsum() + 50,
                "macd": np.random.randn(n).cumsum(),
                "volume_ratio": np.random.randn(n).cumsum() + 1,
            }
        )
        primary_signals = pd.Series(np.random.choice([1, -1, 0], n), index=features.index)
        forward_returns = pd.Series(np.random.randn(n) * 0.02, index=features.index)
        return features, primary_signals, forward_returns

    def test_init(self):
        engine = AIFactorEngine()
        assert engine.model_type == "random_forest"
        assert engine._model is None

    def test_meta_label_returns_result(self, sample_data):
        features, primary_signals, forward_returns = sample_data
        engine = AIFactorEngine()
        result = engine.meta_label(features, primary_signals, forward_returns)
        assert isinstance(result, MetaLabelResult)
        assert isinstance(result.predictions, pd.Series)
        assert isinstance(result.probability, pd.Series)
        assert isinstance(result.precision, float)
        assert isinstance(result.recall, float)
        assert isinstance(result.accuracy, float)

    def test_meta_label_insufficient_data(self):
        engine = AIFactorEngine()
        features = pd.DataFrame({"a": [1, 2, 3]})
        primary = pd.Series([1, -1, 0])
        returns = pd.Series([0.01, -0.01, 0.0])
        result = engine.meta_label(features, primary, returns)
        assert result.precision == 0.0
        assert result.recall == 0.0

    def test_meta_label_feature_importance(self, sample_data):
        features, primary_signals, forward_returns = sample_data
        engine = AIFactorEngine()
        result = engine.meta_label(features, primary_signals, forward_returns)
        assert isinstance(result.feature_importance, dict)
        assert len(result.feature_importance) > 0

    def test_compute_factor(self, sample_data):
        features, _, forward_returns = sample_data
        engine = AIFactorEngine()
        result = engine.compute_factor(features, forward_returns)
        assert isinstance(result, pd.Series)
        assert len(result) == len(features)

    def test_compute_factor_insufficient_data(self):
        engine = AIFactorEngine()
        features = pd.DataFrame({"a": [1, 2, 3]})
        returns = pd.Series([0.01, -0.01, 0.0])
        result = engine.compute_factor(features, returns)
        assert isinstance(result, pd.Series)

    def test_feature_selection(self, sample_data):
        features, _, _ = sample_data
        target = pd.Series(np.random.choice([0, 1], len(features)), index=features.index)
        engine = AIFactorEngine()
        selected = engine.feature_selection(features, target, n_top=2)
        assert isinstance(selected, list)
        assert len(selected) <= 2

    def test_feature_selection_insufficient_data(self):
        engine = AIFactorEngine()
        features = pd.DataFrame({"a": [1], "b": [2]})
        target = pd.Series([1])
        selected = engine.feature_selection(features, target, n_top=2)
        assert isinstance(selected, list)
