"""Sentiment analyzer — FinBERT-based crypto news sentiment.

Uses a pre-trained financial NLP model to score news sentiment
as a trading signal factor.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# ISS-040: a genuinely-neutral sentence yields ~{0.33, 0.33, 0.34}. The prior
# error / no-model path returned this SAME distribution, so the daily-mean
# factor could not tell "model failed" from "genuinely ambivalent text" —
# failures injected a neutral bias. Both error paths now return NaN scores;
# aggregators skip non-finite rows (pandas mean skips NaN by default),
# reserving the neutral distribution for real model output only.
_ERROR_SENTINEL = {"positive": float("nan"), "negative": float("nan"), "neutral": float("nan")}


class SentimentAnalyzer:
    """Analyze news/sentiment for trading signals using FinBERT / FinGPT.

    P2.2 (F11): ``model_name`` selects the backend — a sequence-classification
    model (FinBERT, default) or a generative LM (GPT-2/FinGPT-style causal
    models such as ``rezacsedu/financial_sentiment_analysis_gpt2_model``).
    Generative backends score via a label prompt + keyword extraction;
    unparseable output degrades to the NaN sentinel (ISS-040 contract).
    """

    def __init__(self, model_name: str = "ProsusAI/finbert") -> None:
        self._model_name = model_name
        self._model = None
        self._tokenizer = None
        self._device = "cpu"
        self._generative = False

    def load_model(self, device: str = "cpu") -> None:
        """Load the sentiment model and tokenizer.

        P2.2: generative backends (GPT-2 / FinGPT-style causal LMs) load via
        ``AutoModelForCausalLM`` and score through ``generate``; everything
        else keeps the sequence-classification path.
        """
        try:
            from transformers import AutoTokenizer

            self._device = device
            tokenizer = AutoTokenizer.from_pretrained(self._model_name)
            name = self._model_name.lower()
            if any(k in name for k in ("gpt2", "gpt", "fingpt", "llama", "qwen", "mistral")):
                # Stepwise import: generative backends load via CausalLM; the
                # classification path must not require that class to exist.
                from transformers import AutoModelForCausalLM

                model = AutoModelForCausalLM.from_pretrained(self._model_name)
                self._generative = True
                logger.info("Generative sentiment model loaded on %s", device)
            else:
                from transformers import AutoModelForSequenceClassification

                model = AutoModelForSequenceClassification.from_pretrained(self._model_name)
                self._generative = False
                logger.info("Sequence-classification sentiment model loaded on %s", device)
            model.to(device)
            model.eval()
            self._tokenizer = tokenizer
            self._model = model
        except ImportError:
            logger.warning(
                "transformers/torch not installed. Install: pip install transformers torch"
            )
        except Exception as e:
            logger.error("Failed to load sentiment model: %s", e)

    def analyze_text(self, text: str, reach: float | None = None) -> dict[str, float]:
        """Analyze sentiment of a single text.

        P2.3 (F12, AAAI 2025): ``reach`` is the propagation-breadth metadata
        (cluster reach / influence weight, 0..1). The FinBERT classification
        itself is text-only — reach is validated here and consumed by the
        weighted aggregation paths (``compute_sentiment_factor`` with a
        ``reach`` column). Default None = zero behavior change.

        Returns dict with positive, negative, neutral scores.
        """
        if reach is not None and not (0.0 <= reach <= 1.0):
            raise ValueError(f"reach must be in [0, 1], got {reach!r}")
        if not self._model or not self._tokenizer:
            return _ERROR_SENTINEL
        if self._generative:
            return self._analyze_generative(text)

        try:
            import torch

            inputs = self._tokenizer(
                text, return_tensors="pt", truncation=True, max_length=512, padding=True
            )
            inputs = {k: v.to(self._device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = self._model(**inputs)
                probs = torch.softmax(outputs.logits, dim=-1).cpu().numpy()[0]

            labels = ["positive", "negative", "neutral"]
            result = {labels[i]: float(probs[i]) for i in range(len(labels))}
            return result
        except Exception as e:
            logger.error("Sentiment analysis failed: %s", e)
            return _ERROR_SENTINEL

    def _analyze_generative(self, text: str) -> dict[str, float]:
        """Score via a generative LM (P2.2): label prompt + keyword parse.

        The model completes ``Sentiment:`` with a label word; the answer is
        mapped to a one-hot distribution over positive/negative/neutral.
        Unparseable output returns the NaN sentinel (fail-closed — never a
        fabricated neutral bias, ISS-040 contract).
        """
        if not self._model or not self._tokenizer:
            return _ERROR_SENTINEL
        try:
            import torch

            prompt = (
                "Classify the sentiment of this financial news as positive, "
                "negative, or neutral.\n"
                f"News: {text}\nSentiment:"
            )
            inputs = self._tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)
            inputs = {k: v.to(self._device) for k, v in inputs.items()}
            with torch.no_grad():
                outputs = self._model.generate(
                    **inputs, max_new_tokens=8, do_sample=False, pad_token_id=50256
                )
            answer = (
                self._tokenizer.decode(
                    outputs[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True
                )
                .strip()
                .lower()
            )
        except Exception as e:
            logger.error("Generative sentiment analysis failed: %s", e)
            return _ERROR_SENTINEL

        labels = {"positive": 0.0, "negative": 0.0, "neutral": 0.0}
        for key in labels:
            if key in answer:
                labels[key] = 1.0
        if sum(labels.values()) == 0:
            logger.warning("Generative sentiment output unparseable: %r (sentinel NaN)", answer)
            return _ERROR_SENTINEL
        return labels

    def analyze_batch(
        self, texts: list[str], reaches: list[float] | None = None
    ) -> list[dict[str, float]]:
        """Analyze sentiment for a batch of texts.

        P2.3: ``reaches`` optionally carries the per-text propagation breadth;
        None = no metadata (existing callers unaffected).
        """
        if reaches is not None:
            if len(reaches) != len(texts):
                raise ValueError("reaches must align with texts (same length)")
            return [self.analyze_text(t, reach=r) for t, r in zip(texts, reaches, strict=True)]
        return [self.analyze_text(t) for t in texts]

    def sentiment_score(self, text: str, reach: float | None = None) -> float:
        """Get a single sentiment score: positive - negative.

        Range: [-1.0, 1.0]. ``reach`` is validated but does not alter the
        single-text score (propagation breadth applies at aggregation).
        """
        scores = self.analyze_text(text, reach=reach)
        return scores["positive"] - scores["negative"]

    @staticmethod
    def _weighted_daily_mean(frame: pd.DataFrame, reach_col: str = "reach") -> pd.Series:
        """Reach-weighted daily mean (P2.3): high-influence items dominate.

        weight = score * reach; weighted mean = sum(weight) / sum(reach) per
        group. NaN scores are skipped (existing NaN-sentinel contract).
        """
        valid = frame["score"].notna()
        frame = frame[valid]
        if frame.empty:
            return pd.Series(dtype=float)
        reach = frame[reach_col].fillna(0.0)
        weighted = frame["score"] * reach
        grouped = weighted.groupby(frame["date"]).sum() / reach.groupby(frame["date"]).sum()
        return grouped.replace([float("inf"), float("-inf")], float("nan"))

    def compute_sentiment_factor(self, news_df: pd.DataFrame) -> pd.Series:
        """Compute daily sentiment factor from news DataFrame.

        Expected columns: 'date', 'title' or 'text'. P2.3: when a ``reach``
        column exists (propagation breadth 0..1), the daily mean is weighted
        by it; otherwise the plain daily mean (backward compatible).
        """
        text_col = "title" if "title" in news_df.columns else "text"
        if text_col not in news_df.columns:
            logger.error("News DataFrame must have 'title' or 'text' column")
            return pd.Series(dtype=float)

        scores = news_df[text_col].apply(self.sentiment_score)

        if "date" not in news_df.columns:
            return scores
        daily = pd.DataFrame({"date": news_df["date"], "score": scores})
        if "reach" in news_df.columns:
            daily["reach"] = news_df["reach"]
            return self._weighted_daily_mean(daily)
        return daily.groupby("date")["score"].mean()


class NewsCollector:
    """Collect crypto news from free sources."""

    def __init__(self) -> None:
        self._sources: list[str] = []

    def add_source(self, name: str) -> None:
        self._sources.append(name)

    async def fetch_news(self, query: str = "Bitcoin crypto", max_items: int = 50) -> pd.DataFrame:
        """Fetch recent news articles from registered sources.

        Returns DataFrame with 'date', 'title', 'source' columns.
        """
        try:
            import feedparser
        except ImportError:
            logger.warning("feedparser not installed. Install: pip install feedparser")
            return pd.DataFrame()

        articles = []

        # Fetch from all registered sources plus default CryptoPanic
        sources_to_fetch = list(self._sources)
        if "cryptopanic" not in sources_to_fetch:
            sources_to_fetch.append("cryptopanic")

        for source_name in sources_to_fetch:
            try:
                if source_name == "cryptopanic":
                    feed = feedparser.parse("https://cryptopanic.com/news/rss/?filter=hot")
                    for entry in feed.entries[:max_items]:
                        articles.append(
                            {
                                "date": entry.get("published", ""),
                                "title": entry.get("title", ""),
                                "source": "cryptopanic",
                            }
                        )
                elif source_name == "coindesk":
                    feed = feedparser.parse("https://www.coindesk.com/arc/outboundfeeds/rss/")
                    for entry in feed.entries[:max_items]:
                        articles.append(
                            {
                                "date": entry.get("published", ""),
                                "title": entry.get("title", ""),
                                "source": "coindesk",
                            }
                        )
                else:
                    logger.warning("Unknown source: %s", source_name)
            except Exception as e:
                logger.warning("%s RSS failed: %s", source_name, e)

        if not articles:
            return pd.DataFrame()

        df = pd.DataFrame(articles)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        return df
