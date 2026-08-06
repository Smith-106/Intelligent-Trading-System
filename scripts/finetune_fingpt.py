#!/usr/bin/env python3
"""FinGPT sentiment fine-tuning entry point (P2.2, F11).

Single-GPU / CPU fine-tuning of a financial-sentiment LM from a labeled news
CSV. Defaults target the CPU-friendly GPT-2-scale path (RTX-3090-class GPUs
can raise ``--model`` to the official FinGPT 7B LoRA base).

Environment prerequisites (not installed by this script):
    pip install torch transformers datasets accelerate

GPU availability is detected at runtime (cuda > mps > cpu) and printed; the
script itself runs on CPU if no accelerator is present — large models (7B+)
require an NVIDIA GPU and will be slow/impractical on CPU.

Usage:
    python scripts/finetune_fingpt.py --data news_labeled.csv
    python scripts/finetune_fingpt.py --data news_labeled.csv --epochs 3 --lr 2e-5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

LABEL_MAP = {"negative": 0, "neutral": 1, "positive": 2}


def _pick_device() -> str:
    """cuda > mps > cpu (printed; caller may override with --device)."""
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            return "mps"
        return "cpu"
    except ImportError:
        return "cpu"


def _load_dataset(path: Path) -> tuple[list[str], list[int]]:
    """Load labeled news CSV (columns: text, label) into (texts, label_ids)."""
    import pandas as pd

    df = pd.read_csv(path)
    if "text" not in df.columns or "label" not in df.columns:
        raise SystemExit(
            "CSV must have 'text' and 'label' columns (label: negative/neutral/positive)"
        )
    texts = df["text"].dropna().astype(str).tolist()
    labels = df["label"].dropna().astype(str).map(LABEL_MAP)
    if labels.isna().any():
        raise SystemExit("CSV contains labels outside {negative, neutral, positive}")
    return texts, labels.astype(int).tolist()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", required=True, help="labeled news CSV (text, label)")
    ap.add_argument(
        "--model",
        default="rezacsedu/financial_sentiment_analysis_gpt2_model",
        help="base model (GPT-2-scale for CPU; FinGPT 7B LoRA base for GPU)",
    )
    ap.add_argument("--output", default="data/fingpt_finetuned", help="output dir")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--device", default=None, help="override device auto-detection")
    args = ap.parse_args()

    device = args.device or _pick_device()
    print(f"[finetune] device: {device}")
    if device == "cpu":
        print(
            "[finetune] WARNING: CPU training — GPT-2-scale models only; "
            "7B+ FinGPT LoRA requires an NVIDIA GPU (RTX 3090-class)."
        )
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as e:
        raise SystemExit(
            "Missing ML deps; install: pip install torch transformers datasets accelerate"
        ) from e

    data_path = Path(args.data)
    if not data_path.exists():
        raise SystemExit(f"Data file not found: {data_path}")
    texts, labels = _load_dataset(data_path)
    print(f"[finetune] dataset: {len(texts)} rows, labels {sorted(set(labels))}")

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(args.model, num_labels=3).to(device)

    encodings = tokenizer(texts, truncation=True, padding=True, max_length=512, return_tensors="pt")
    encodings = {k: v.to(device) for k, v in encodings.items()}
    labels_t = torch.tensor(labels, device=device)
    dataset = torch.utils.data.TensorDataset(
        encodings["input_ids"], encodings["attention_mask"], labels_t
    )
    loader = torch.utils.data.DataLoader(dataset, batch_size=args.batch_size, shuffle=True)

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    model.train()
    for epoch in range(args.epochs):
        total_loss = 0.0
        for _step, (input_ids, attention_mask, batch_labels) in enumerate(loader):
            optimizer.zero_grad()
            outputs = model(input_ids=input_ids, attention_mask=attention_mask, labels=batch_labels)
            outputs.loss.backward()
            optimizer.step()
            total_loss += float(outputs.loss.item())
        print(
            f"[finetune] epoch {epoch + 1}/{args.epochs} loss={total_loss / max(_step + 1, 1):.4f}"
        )

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out)
    tokenizer.save_pretrained(out)
    print(f"[finetune] saved to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
