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
FIN_GOLD: list[tuple[str, str]] = [
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

GOLD = FIN_GOLD


def _predict(model: Any, tok: Any, text: str, neutral_floor: float = 0.0) -> str:
    """Argmax prediction; with neutral_floor > 0, re-label high-neutral
    outputs as the stronger of positive/negative (domain calibration for
    conservative checkpoints)."""
    ids = tok(text, return_tensors="pt", truncation=True, max_length=512)
    with torch.no_grad():
        logits = model(**ids).logits
    probs = torch.softmax(logits, dim=-1)[0]
    id2label = model.config.id2label
    labels = {i: str(id2label.get(i) or id2label.get(str(i), str(i))) for i in range(probs.shape[0])}
    neutral_idx = next((i for i, lbl in labels.items() if lbl == "neutral"), None)
    if neutral_floor > 0.0 and neutral_idx is not None:
        pn = float(probs[neutral_idx])
        if pn < neutral_floor:
            pos_idx = next((i for i, lbl in labels.items() if lbl == "positive"), None)
            neg_idx = next((i for i, lbl in labels.items() if lbl == "negative"), None)
            if pos_idx is not None and neg_idx is not None:
                return "positive" if float(probs[pos_idx]) > float(probs[neg_idx]) else "negative"
    idx = int(probs.argmax(dim=-1))
    return labels[idx]


def _evaluate(model_id: str, neutral_floor: float = 0.0) -> tuple[float, list[tuple[str, str, str]]]:
    tok: Any = AutoTokenizer.from_pretrained(model_id)
    model: Any = AutoModelForSequenceClassification.from_pretrained(model_id)
    model.eval()
    hits = 0
    detail: list[tuple[str, str, str]] = []
    for text, gold in GOLD:
        pred = _predict(model, tok, text, neutral_floor)
        hit = pred == gold
        hits += int(hit)
        detail.append((text[:52], gold, pred))
    return hits / len(GOLD), detail


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--models", nargs="+", default=None, help="override candidate list")
    ap.add_argument(
        "--crypto-gold",
        action="store_true",
        help="also evaluate against the crypto-domain gold set "
        "(scripts/domain_gold_crypto.json; OKX announcements + CT/CD headlines)",
    )
    ap.add_argument(
        "--calibrate",
        type=float,
        default=0.0,
        help="re-label outputs with neutral prob < this floor as pos/neg "
        "argmax (domain calibration; try 0.5-0.95)",
    )
    args = ap.parse_args()

    global GOLD
    if args.crypto_gold:
        import json

        with open(REPO_ROOT / "scripts" / "domain_gold_crypto.json", encoding="utf-8") as f:
            GOLD = [tuple(pair) for pair in json.load(f)["gold"]]

    models = args.models or [m for m, _ in CANDIDATES]
    results: list[tuple[float, str, list[tuple[str, str, str]]]] = []
    for model_id in [BASELINE, *models]:
        print(f"[eval] {model_id} ...")
        acc, detail = _evaluate(model_id, args.calibrate)
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
