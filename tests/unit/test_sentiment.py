"""Tests for sentiment module — with graceful degradation for missing transformers."""

from __future__ import annotations

import math
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
        # ISS-040: no model → NaN sentinel (NOT the neutral {0.33,0.33,0.34}
        # distribution, which collides with genuine neutral). Aggregators skip NaN.
        sa = SentimentAnalyzer()
        result = sa.analyze_text("Bitcoin is going up")
        assert "positive" in result
        assert "negative" in result
        assert "neutral" in result
        assert all(math.isnan(v) for v in result.values())

    def test_sentiment_score_without_model(self):
        # ISS-040: NaN - NaN = NaN (not a neutral 0.0) — distinguishable from
        # genuine neutral so the daily-mean factor skips model-failure rows.
        sa = SentimentAnalyzer()
        score = sa.sentiment_score("Bitcoin is going up")
        assert isinstance(score, float)
        assert math.isnan(score)

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

        # ISS-040: inference failure → NaN sentinel, not the neutral distribution.
        assert all(math.isnan(v) for v in result.values())

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


class TestReachPropagationBreadth:
    """P2.3 (F12): propagation-breadth metadata — validated, aggregation
    weighted, zero behavior change when absent."""

    def test_analyze_text_accepts_reach_and_validates(self) -> None:
        from quantflow.strategy.sentiment import SentimentAnalyzer

        analyzer = SentimentAnalyzer()
        # No model loaded: reach is validated first, then the NaN sentinel.
        result = analyzer.analyze_text("any text", reach=0.5)
        assert all(v != v for v in result.values())  # NaN sentinel (no model)
        with pytest.raises(ValueError):
            analyzer.analyze_text("any text", reach=1.5)
        with pytest.raises(ValueError):
            analyzer.analyze_text("any text", reach=-0.1)

    def test_analyze_batch_reaches_alignment(self) -> None:
        from quantflow.strategy.sentiment import SentimentAnalyzer

        analyzer = SentimentAnalyzer()
        results = analyzer.analyze_batch(["a", "b"], reaches=[0.1, 0.9])
        assert len(results) == 2
        with pytest.raises(ValueError):
            analyzer.analyze_batch(["a", "b"], reaches=[0.1])

    def test_compute_sentiment_factor_reach_weighted_mean(self, monkeypatch) -> None:
        """High-reach items dominate the daily mean; NaN scores skipped."""

        from quantflow.strategy.sentiment import SentimentAnalyzer

        analyzer = SentimentAnalyzer()
        # Fake model-less score path: sentiment_score returns NaN -> we stub
        # sentiment_score directly so the aggregation math is testable.
        monkeypatch.setattr(
            analyzer,
            "sentiment_score",
            lambda text, reach=None: float(text),  # score == numeric text
        )
        news = pd.DataFrame(
            {
                "date": ["2026-08-01", "2026-08-01", "2026-08-01", "2026-08-02"],
                "text": ["1.0", "0.0", "0.5", "0.5"],  # scores
                "reach": [0.9, 0.1, 0.5, 1.0],
            }
        )
        daily = analyzer.compute_sentiment_factor(news)
        assert "2026-08-01" in daily.index
        # weighted = (1.0*0.9 + 0.0*0.1 + 0.5*0.5) / (0.9+0.1+0.5) = 1.15/1.5
        assert daily["2026-08-01"] == pytest.approx(1.15 / 1.5)
        # Plain mean would be (1.0+0.0+0.5)/3 = 0.5 — weighted differs.
        assert daily["2026-08-02"] == pytest.approx(0.5)

    def test_compute_sentiment_factor_without_reach_unchanged(self) -> None:
        """No reach column -> plain daily mean (backward compatible)."""
        from quantflow.strategy.sentiment import SentimentAnalyzer

        analyzer = SentimentAnalyzer()
        news = pd.DataFrame(
            {"date": ["2026-08-01", "2026-08-01", "2026-08-02"], "text": ["x", "y", "z"]}
        )
        daily = analyzer.compute_sentiment_factor(news)
        assert set(daily.index) == {"2026-08-01", "2026-08-02"}
        assert daily["2026-08-01"] != daily["2026-08-01"]  # NaN sentinel -> NaN

    def test_weighted_mean_skips_nan_scores(self) -> None:
        """NaN scores (error sentinel) must not poison the weighted mean."""

        from quantflow.strategy.sentiment import SentimentAnalyzer

        analyzer = SentimentAnalyzer()
        analyzer.sentiment_score = lambda text, reach=None: (  # type: ignore[method-assign]
            float("nan") if text == "bad" else float(text)
        )
        news = pd.DataFrame(
            {
                "date": ["2026-08-01", "2026-08-01", "2026-08-01"],
                "text": ["bad", "0.4", "0.8"],
                "reach": [1.0, 0.5, 0.5],
            }
        )
        daily = analyzer.compute_sentiment_factor(news)
        assert daily["2026-08-01"] == pytest.approx((0.4 * 0.5 + 0.8 * 0.5) / 1.0)


class TestFinGptBackend:
    """P2.2 (F11): generative-LM backend — load path dispatch, prompt-based
    scoring, fail-closed unparseable output."""

    def test_generative_model_name_selects_causal_lm(self, monkeypatch) -> None:
        import sys
        from types import SimpleNamespace

        from quantflow.strategy.sentiment import SentimentAnalyzer

        loaded: dict = {}
        fake_tok = SimpleNamespace(decode=lambda ids, **kw: " positive")

        class FakeCausalModel:
            @classmethod
            def from_pretrained(cls, name):
                return cls()

            def __init__(self, *a, **k):
                loaded["cls"] = "causal"

            def to(self, device):
                return self

            def eval(self):
                return self

        class FakeSeqModel(FakeCausalModel):
            def __init__(self, *a, **k):
                loaded["cls"] = "seq"

        from types import ModuleType

        fake_transformers = ModuleType("transformers")
        fake_transformers.AutoModelForCausalLM = FakeCausalModel
        fake_transformers.AutoModelForSequenceClassification = FakeSeqModel
        fake_transformers.AutoTokenizer = SimpleNamespace(from_pretrained=lambda name: fake_tok)
        monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

        analyzer = SentimentAnalyzer(model_name="someorg/fingpt-gpt2-model")
        analyzer.load_model()
        assert loaded["cls"] == "causal"
        assert analyzer._generative is True

        analyzer2 = SentimentAnalyzer(model_name="ProsusAI/finbert")
        analyzer2.load_model()
        assert loaded["cls"] == "seq"
        assert analyzer2._generative is False

    def test_architecture_override_forces_classification(self, monkeypatch) -> None:
        """Model names are unreliable architecture signals: a name containing
        ``gpt2`` may ship a classification head (e.g. rezacsedu GPT-2
        sentiment checkpoints) — an explicit ``architecture`` override must
        win over keyword sniffing.
        """
        import sys
        from types import ModuleType, SimpleNamespace

        from quantflow.strategy.sentiment import SentimentAnalyzer

        loaded: dict = {}
        fake_tok = SimpleNamespace(decode=lambda ids, **kw: " positive")

        class FakeCausalModel:
            @classmethod
            def from_pretrained(cls, name):
                return cls()

            def __init__(self, *a, **k):
                loaded["cls"] = "causal"

            def to(self, device):
                return self

            def eval(self):
                return self

        class FakeSeqModel(FakeCausalModel):
            def __init__(self, *a, **k):
                loaded["cls"] = "seq"

        fake_transformers = ModuleType("transformers")
        fake_transformers.AutoModelForCausalLM = FakeCausalModel
        fake_transformers.AutoModelForSequenceClassification = FakeSeqModel
        fake_transformers.AutoTokenizer = SimpleNamespace(from_pretrained=lambda name: fake_tok)
        monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

        analyzer = SentimentAnalyzer(
            model_name="someorg/fingpt-gpt2-model", architecture="classification"
        )
        analyzer.load_model()
        assert loaded["cls"] == "seq"
        assert analyzer._generative is False

        # Explicit causal override on a finbert-looking name.
        analyzer2 = SentimentAnalyzer(model_name="org/finbert", architecture="causal")
        analyzer2.load_model()
        assert loaded["cls"] == "causal"
        assert analyzer2._generative is True

    def test_generative_scoring_parses_label(self, monkeypatch) -> None:
        import contextlib
        import sys
        from types import ModuleType, SimpleNamespace

        import numpy as np

        from quantflow.strategy.sentiment import SentimentAnalyzer

        class FakeTensor:
            """Torch-tensor-shaped stub: .to()/shape/indexing."""

            def __init__(self, arr):
                self._arr = np.asarray(arr)

            def to(self, device):
                return self

            @property
            def shape(self):
                return self._arr.shape

            def __getitem__(self, key):
                return self._arr[key]

        answers = iter(["negative"])

        class FakeModel:
            @staticmethod
            def from_pretrained(name):
                return FakeModel()

            def generate(self, **kwargs):
                # outputs[0][input_len:] -> array([9]); decode is stubbed.
                return [np.array([1, 2, 3, 9])]

        fake_tok = SimpleNamespace(decode=lambda ids, **kw: next(answers))

        fake_transformers = ModuleType("transformers")
        fake_transformers.AutoModelForCausalLM = FakeModel
        fake_transformers.AutoModelForSequenceClassification = FakeModel
        fake_transformers.AutoTokenizer = SimpleNamespace(from_pretrained=lambda name: fake_tok)
        monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
        monkeypatch.setitem(
            sys.modules,
            "torch",
            SimpleNamespace(no_grad=contextlib.nullcontext),
        )

        class FakeTokenizer:
            def __call__(self, *a, **k):
                return {
                    "input_ids": FakeTensor([[1, 2, 3]]),
                    "attention_mask": FakeTensor([[1, 1, 1]]),
                }

            def decode(self, ids, **kw):
                return next(answers)

        analyzer = SentimentAnalyzer(model_name="org/fingpt-gpt2")
        analyzer.load_model()
        analyzer._tokenizer = FakeTokenizer()
        analyzer._model = FakeModel()
        analyzer._device = "cpu"
        result = analyzer._analyze_generative("BTC rallies")
        assert result["negative"] == 1.0
        assert result["positive"] == 0.0

    def test_generative_unparseable_output_returns_nan(self, monkeypatch) -> None:
        import numpy as np

        from quantflow.strategy.sentiment import SentimentAnalyzer

        class FakeTensor:
            def __init__(self, arr):
                self._arr = np.asarray(arr)

            def to(self, device):
                return self

            @property
            def shape(self):
                return self._arr.shape

            def __getitem__(self, key):
                return self._arr[key]

        class FakeModel:
            def generate(self, **kwargs):
                return [np.array([1, 2, 3, 9])]

        class FakeTokenizer:
            def __call__(self, *a, **k):
                return {"input_ids": FakeTensor([[1, 2, 3]])}

            def decode(self, ids, **kw):
                return "???"

        analyzer = SentimentAnalyzer(model_name="org/fingpt-gpt2")
        analyzer._generative = True
        analyzer._model = FakeModel()
        analyzer._tokenizer = FakeTokenizer()
        analyzer._device = "cpu"
        result = analyzer._analyze_generative("gibberish")
        assert all(v != v for v in result.values())  # NaN sentinel
