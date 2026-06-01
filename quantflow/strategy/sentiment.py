"""Sentiment analyzer — FinBERT-based crypto news sentiment.

Uses a pre-trained financial NLP model to score news sentiment
as a trading signal factor.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    """Analyze news/sentiment for trading signals using FinBERT."""

    def __init__(self, model_name: str = "ProsusAI/finbert") -> None:
        self._model_name = model_name
        self._model = None
        self._tokenizer = None
        self._device = "cpu"

    def load_model(self, device: str = "cpu") -> None:
        """Load FinBERT model and tokenizer."""
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            self._device = device
            self._tokenizer = AutoTokenizer.from_pretrained(self._model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(self._model_name)
            self._model.to(device)
            self._model.eval()
            logger.info("FinBERT loaded on %s", device)
        except ImportError:
            logger.warning("transformers/torch not installed. Install: pip install transformers torch")
        except Exception as e:
            logger.error("Failed to load FinBERT: %s", e)

    def analyze_text(self, text: str) -> dict[str, float]:
        """Analyze sentiment of a single text.

        Returns dict with positive, negative, neutral scores.
        """
        if not self._model or not self._tokenizer:
            return {"positive": 0.33, "negative": 0.33, "neutral": 0.34}

        try:
            import torch

            inputs = self._tokenizer(text, return_tensors="pt", truncation=True,
                                     max_length=512, padding=True)
            inputs = {k: v.to(self._device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = self._model(**inputs)
                probs = torch.softmax(outputs.logits, dim=-1).cpu().numpy()[0]

            labels = ["positive", "negative", "neutral"]
            result = {labels[i]: float(probs[i]) for i in range(len(labels))}
            return result
        except Exception as e:
            logger.error("Sentiment analysis failed: %s", e)
            return {"positive": 0.33, "negative": 0.33, "neutral": 0.34}

    def analyze_batch(self, texts: list[str]) -> list[dict[str, float]]:
        """Analyze sentiment for a batch of texts."""
        return [self.analyze_text(t) for t in texts]

    def sentiment_score(self, text: str) -> float:
        """Get a single sentiment score: positive - negative.

        Range: [-1.0, 1.0]
        """
        scores = self.analyze_text(text)
        return scores["positive"] - scores["negative"]

    def compute_sentiment_factor(self, news_df: pd.DataFrame) -> pd.Series:
        """Compute daily sentiment factor from news DataFrame.

        Expected columns: 'date', 'title' or 'text'
        """
        text_col = "title" if "title" in news_df.columns else "text"
        if text_col not in news_df.columns:
            logger.error("News DataFrame must have 'title' or 'text' column")
            return pd.Series(dtype=float)

        scores = news_df[text_col].apply(self.sentiment_score)

        if "date" in news_df.columns:
            daily = pd.DataFrame({"date": news_df["date"], "score": scores})
            daily = daily.groupby("date")["score"].mean()
            return daily
        return scores


class NewsCollector:
    """Collect crypto news from free sources."""

    def __init__(self) -> None:
        self._sources: list[str] = []

    def add_source(self, name: str) -> None:
        self._sources.append(name)

    async def fetch_news(self, query: str = "Bitcoin crypto",
                         max_items: int = 50) -> pd.DataFrame:
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
                        articles.append({
                            "date": entry.get("published", ""),
                            "title": entry.get("title", ""),
                            "source": "cryptopanic",
                        })
                elif source_name == "coindesk":
                    feed = feedparser.parse("https://www.coindesk.com/arc/outboundfeeds/rss/")
                    for entry in feed.entries[:max_items]:
                        articles.append({
                            "date": entry.get("published", ""),
                            "title": entry.get("title", ""),
                            "source": "coindesk",
                        })
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
