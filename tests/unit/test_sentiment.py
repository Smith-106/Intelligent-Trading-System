"""Tests for sentiment module — with graceful degradation for missing transformers."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from quantflow.strategy.sentiment import NewsCollector, SentimentAnalyzer


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
        news_df = pd.DataFrame(
            {
                "date": ["2024-01-01", "2024-01-01", "2024-01-02"],
                "title": ["Bitcoin surges", "Crypto crash", "Market stable"],
            }
        )
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

    def test_load_model_success_sets_runtime_objects(self, monkeypatch: pytest.MonkeyPatch):
        sa = SentimentAnalyzer()

        class FakeTokenizer:
            @classmethod
            def from_pretrained(cls, model_name: str):
                assert model_name == "ProsusAI/finbert"
                return cls()

        class FakeModel:
            def __init__(self) -> None:
                self.device = None
                self.evaluated = False

            @classmethod
            def from_pretrained(cls, model_name: str):
                assert model_name == "ProsusAI/finbert"
                return cls()

            def to(self, device: str) -> None:
                self.device = device

            def eval(self) -> None:
                self.evaluated = True

        transformers = ModuleType("transformers")
        transformers.AutoTokenizer = FakeTokenizer
        transformers.AutoModelForSequenceClassification = FakeModel
        monkeypatch.setitem(sys.modules, "transformers", transformers)

        sa.load_model(device="cuda")

        assert isinstance(sa._tokenizer, FakeTokenizer)
        assert isinstance(sa._model, FakeModel)
        assert sa._model.device == "cuda"
        assert sa._model.evaluated is True
        assert sa._device == "cuda"

    def test_load_model_handles_runtime_errors(self, monkeypatch: pytest.MonkeyPatch):
        sa = SentimentAnalyzer()

        class BrokenTokenizer:
            @classmethod
            def from_pretrained(cls, model_name: str):
                raise RuntimeError("download failed")

        class FakeModel:
            @classmethod
            def from_pretrained(cls, model_name: str):
                return cls()

        transformers = ModuleType("transformers")
        transformers.AutoTokenizer = BrokenTokenizer
        transformers.AutoModelForSequenceClassification = FakeModel
        monkeypatch.setitem(sys.modules, "transformers", transformers)

        sa.load_model()

        assert sa._tokenizer is None
        assert sa._model is None

    def test_analyze_text_with_loaded_model(self, monkeypatch: pytest.MonkeyPatch):
        sa = SentimentAnalyzer()

        class FakeTensor:
            def __init__(self, payload):
                self.payload = payload

            def to(self, device: str):
                return self

            def cpu(self):
                return self

            def numpy(self):
                return [self.payload]

        class FakeTokenizer:
            def __call__(self, text: str, **kwargs):
                assert text == "Bullish breakout"
                assert kwargs["return_tensors"] == "pt"
                return {"input_ids": FakeTensor([1, 2, 3])}

        class FakeModel:
            def __call__(self, **inputs):
                assert "input_ids" in inputs
                return SimpleNamespace(logits="logits")

        @contextmanager
        def fake_no_grad():
            yield

        torch_module = ModuleType("torch")
        torch_module.no_grad = fake_no_grad
        torch_module.softmax = lambda logits, dim=-1: FakeTensor([0.7, 0.1, 0.2])
        monkeypatch.setitem(sys.modules, "torch", torch_module)

        sa._tokenizer = FakeTokenizer()
        sa._model = FakeModel()

        result = sa.analyze_text("Bullish breakout")

        assert result == {"positive": 0.7, "negative": 0.1, "neutral": 0.2}

    def test_analyze_text_falls_back_when_inference_errors(self, monkeypatch: pytest.MonkeyPatch):
        sa = SentimentAnalyzer()

        class BrokenTokenizer:
            def __call__(self, text: str, **kwargs):
                raise RuntimeError("tokenization failed")

        @contextmanager
        def fake_no_grad():
            yield

        torch_module = ModuleType("torch")
        torch_module.no_grad = fake_no_grad
        monkeypatch.setitem(sys.modules, "torch", torch_module)

        sa._tokenizer = BrokenTokenizer()
        sa._model = object()

        result = sa.analyze_text("bad input")

        assert result == {"positive": 0.33, "negative": 0.33, "neutral": 0.34}

    def test_compute_sentiment_factor_uses_text_column_without_dates(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        sa = SentimentAnalyzer()
        monkeypatch.setattr(
            sa,
            "sentiment_score",
            lambda text: {"good": 0.8, "bad": -0.4}.get(text, 0.0),
        )
        news_df = pd.DataFrame({"text": ["good", "bad", "flat"]})

        result = sa.compute_sentiment_factor(news_df)

        assert list(result) == [0.8, -0.4, 0.0]


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

    @pytest.mark.asyncio
    async def test_fetch_news_collects_default_and_registered_sources(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        nc = NewsCollector()
        nc.add_source("coindesk")

        def fake_parse(url: str):
            if "cryptopanic" in url:
                entries = [
                    {"published": "2024-01-01T08:00:00Z", "title": "BTC rallies"},
                    {"published": "2024-01-02T08:00:00Z", "title": "ETF optimism"},
                ]
            else:
                entries = [{"published": "2024-01-03T08:00:00Z", "title": "CoinDesk recap"}]
            return SimpleNamespace(entries=entries)

        feedparser = ModuleType("feedparser")
        feedparser.parse = fake_parse
        monkeypatch.setitem(sys.modules, "feedparser", feedparser)

        result = await nc.fetch_news(max_items=1)

        assert list(result["source"]) == ["coindesk", "cryptopanic"]
        assert list(result["title"]) == ["CoinDesk recap", "BTC rallies"]
        assert str(result["date"].iloc[0]) == "2024-01-03"

    @pytest.mark.asyncio
    async def test_fetch_news_ignores_unknown_sources_and_continues_after_failures(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        nc = NewsCollector()
        nc.add_source("unknown")
        nc.add_source("coindesk")

        calls: list[str] = []

        def fake_parse(url: str):
            calls.append(url)
            if "coindesk" in url:
                raise RuntimeError("rss offline")
            return SimpleNamespace(entries=[{"published": "2024-01-04", "title": "panic"}])

        feedparser = ModuleType("feedparser")
        feedparser.parse = fake_parse
        monkeypatch.setitem(sys.modules, "feedparser", feedparser)

        with caplog.at_level("WARNING"):
            result = await nc.fetch_news()

        assert len(result) == 1
        assert result.iloc[0]["source"] == "cryptopanic"
        assert "Unknown source: unknown" in caplog.text
        assert "coindesk RSS failed: rss offline" in caplog.text
        assert any("cryptopanic" in url for url in calls)

    @pytest.mark.asyncio
    async def test_fetch_news_returns_empty_frame_when_sources_yield_no_articles(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        nc = NewsCollector()

        feedparser = ModuleType("feedparser")
        feedparser.parse = lambda url: SimpleNamespace(entries=[])
        monkeypatch.setitem(sys.modules, "feedparser", feedparser)

        result = await nc.fetch_news()

        assert result.empty
