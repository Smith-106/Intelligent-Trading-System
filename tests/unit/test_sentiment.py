"""Tests for sentiment module — with graceful degradation for missing transformers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from quantflow.strategy.sentiment import SentimentAnalyzer, NewsCollector


class TestSentimentAnalyzer:
    """Test SentimentAnalyzer with and without model."""

    def test_init(self):
        sa = SentimentAnalyzer()
        assert sa._model is None
        assert sa._tokenizer is None

    def test_analyze_text_without_model(self):
        sa = SentimentAnalyzer()
        result = sa.analyze_text("Bitcoin is going up")
        assert "positive" in result
        assert "negative" in result
        assert "neutral" in result
        assert abs(sum(result.values()) - 1.0) < 0.01

    def test_sentiment_score_without_model(self):
        sa = SentimentAnalyzer()
        score = sa.sentiment_score("Bitcoin is going up")
        assert isinstance(score, float)
        assert -1.0 <= score <= 1.0

    def test_analyze_batch_without_model(self):
        sa = SentimentAnalyzer()
        results = sa.analyze_batch(["Bitcoin up", "Bitcoin down"])
        assert len(results) == 2
        for r in results:
            assert "positive" in r

    def test_compute_sentiment_factor_with_title(self):
        sa = SentimentAnalyzer()
        news_df = pd.DataFrame({
            "date": ["2024-01-01", "2024-01-01", "2024-01-02"],
            "title": ["Bitcoin surges", "Crypto crash", "Market stable"],
        })
        result = sa.compute_sentiment_factor(news_df)
        assert isinstance(result, (pd.Series, pd.DataFrame))

    def test_compute_sentiment_factor_no_title_or_text(self):
        sa = SentimentAnalyzer()
        news_df = pd.DataFrame({"date": ["2024-01-01"]})
        result = sa.compute_sentiment_factor(news_df)
        assert result.empty

    def test_load_model_missing_transformers(self):
        sa = SentimentAnalyzer()
        with patch.dict("sys.modules", {"transformers": None}):
            sa.load_model()
            assert sa._model is None


class TestNewsCollector:
    """Test NewsCollector source management."""

    def test_init(self):
        nc = NewsCollector()
        assert nc._sources == []

    def test_add_source(self):
        nc = NewsCollector()
        nc.add_source("coindesk")
        nc.add_source("cryptocompare")
        assert len(nc._sources) == 2
        assert "coindesk" in nc._sources
        assert "cryptocompare" in nc._sources

    @pytest.mark.asyncio
    async def test_fetch_news_without_feedparser(self):
        nc = NewsCollector()
        with patch.dict("sys.modules", {"feedparser": None}):
            result = await nc.fetch_news()
            assert isinstance(result, pd.DataFrame)
