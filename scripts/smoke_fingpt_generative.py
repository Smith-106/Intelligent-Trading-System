#!/usr/bin/env python3
"""P2.2 generative-LM smoke test — real small-model inference on CPU.

Verifies the SentimentAnalyzer causal-LM branch end-to-end with a real
HuggingFace model (first run downloads the checkpoint):
    python scripts/smoke_fingpt_generative.py [--model MODEL]

Default: sshleifer/tiny-gpt2 (~30 MB, pure code-path check — generic LM,
sentiment labels are NOT expected to parse reliably).
For a finance-tuned checkpoint (labels likely parse):
    python scripts/smoke_fingpt_generative.py --model rezacsedu/financial_sentiment_analysis_gpt2_model
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quantflow.strategy.sentiment import SentimentAnalyzer  # noqa: E402

SAMPLES = [
    "Bitcoin hits an all-time high as ETF inflows surge",
    "Regulator launches investigation into major exchange",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default="sshleifer/tiny-gpt2")
    args = ap.parse_args()

    analyzer = SentimentAnalyzer(model_name=args.model)
    analyzer.load_model(device="cpu")
    print(f"[smoke] model={args.model} generative={analyzer._generative}")

    # PASS = the generative path executes end-to-end without crashing.
    # Unparseable output -> NaN sentinel is the expected fail-closed contract
    # (ISS-040), NOT a failure: generic/unfinetuned LMs emit no label keywords.
    ok = True
    for text in SAMPLES:
        scores = analyzer.analyze_text(text)
        finite = sum(1 for v in scores.values() if v == v)  # NaN-safe count
        print(f"[smoke] {text!r}\n        -> {scores} finite={finite}")
    print("[smoke] PASS (end-to-end generative path; NaN = fail-closed sentinel)" if ok else "[smoke] FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
