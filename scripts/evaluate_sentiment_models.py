#!/usr/bin/env python3
"""P2.2-C community-weight bake-off — pick the best financial-sentiment model.

Scores candidate community checkpoints against a hand-labeled financial-news
gold set (Financial PhraseBank-style, 3 classes) and prints accuracy per
model. All models are CPU-inference compatible (BERT/RoBERTa scale).

    python scripts/evaluate_sentiment_models.py [--skip-download]

Winner is the model with highest gold-set accuracy (ties broken by HF
downloads); the result is printed and can be recorded in the roadmap.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from typing import Any  # noqa: E402

import torch  # noqa: E402
from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: E402

# (model_id, HF downloads) — gold accuracy breaks ties, downloads break
# accuracy ties.
CANDIDATES = [
    ("ahmedrachid/FinancialBERT-Sentiment-Analysis", 322_557),
    ("mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis", 195_550),
    ("mrm8488/deberta-v3-ft-financial-news-sentiment-analysis", 143_452),
]
BASELINE = "ProsusAI/finbert"

# Hand-labeled gold set (Financial PhraseBank-style short headlines).
GOLD: list[tuple[str, str]] = [
    # positive
    ("Operating profit increased to EUR 22.5 million from EUR 19.4 million in 2007", "positive"),
    ("The company reported record quarterly profits and raised its dividend", "positive"),
    ("Sales growth accelerated for the third consecutive quarter", "positive"),
    ("The group announced a share buyback program of EUR 100 million", "positive"),
    # negative
    ("The company had to write off EUR 5.4 million in goodwill", "negative"),
    ("Net loss widened as restructuring costs mounted", "negative"),
    ("The firm announced 500 job cuts and a profit warning", "negative"),
    ("Liquidity concerns grew after the credit line was withdrawn", "negative"),
    # neutral
    ("The company will release its quarterly report on May 15", "neutral"),
    ("The board announced the date of the annual general meeting", "neutral"),
    ("The group is in negotiations with potential partners", "neutral"),
    ("The management presented its strategy for the coming year", "neutral"),
    # tricky
    ("Despite the difficult environment, the group managed to hold its margins", "positive"),
    ("The outlook remains uncertain after the guidance was withdrawn", "negative"),
    ("The acquisition is subject to regulatory approval", "neutral"),
]


def _predict(model: Any, tok: Any, text: str) -> str:
    ids = tok(text, return_tensors="pt", truncation=True, max_length=512)
    with torch.no_grad():
        logits = model(**ids).logits
    idx = int(torch.softmax(logits, dim=-1).argmax(dim=-1)[0])
    id2label = model.config.id2label
    # Some checkpoints key by int, others by str.
    return str(id2label.get(idx) or id2label.get(str(idx), str(idx)))


def _evaluate(model_id: str) -> tuple[float, list[tuple[str, str, str]]]:
    tok: Any = AutoTokenizer.from_pretrained(model_id)
    model: Any = AutoModelForSequenceClassification.from_pretrained(model_id)
    model.eval()
    hits = 0
    detail: list[tuple[str, str, str]] = []
    for text, gold in GOLD:
        pred = _predict(model, tok, text)
        hit = pred == gold
        hits += int(hit)
        detail.append((text[:52], gold, pred))
    return hits / len(GOLD), detail


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--models", nargs="+", default=None, help="override candidate list")
    args = ap.parse_args()

    models = args.models or [m for m, _ in CANDIDATES]
    results: list[tuple[float, str, list[tuple[str, str, str]]]] = []
    for model_id in [BASELINE, *models]:
        print(f"[eval] {model_id} ...")
        acc, detail = _evaluate(model_id)
        results.append((acc, model_id, detail))
        print(f"  accuracy = {acc:.1%} ({int(acc * len(GOLD))}/{len(GOLD)})")
        for text, gold, pred in detail:
            if gold != pred:
                print(f"    MISMATCH {text!r} gold={gold} pred={pred}")

    results.sort(
        key=lambda r: (
            -r[0],
            -[m for m, _ in CANDIDATES].index(r[1]) if r[1] in [m for m, _ in CANDIDATES] else -1,
        )
    )
    print("\n=== ranking ===")
    for acc, mid, _ in results:
        print(f"  {acc:.1%}  {mid}")
    print(f"\nWinner: {results[0][1]} ({results[0][0]:.1%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
