#!/usr/bin/env python3
"""CLI entry for KOL Discord ingest + consensus (advisory).

Examples
--------
  # Offline export (DiscordChatExporter JSON)
  python scripts/kol_discord_ingest.py export path/to/channel.json

  # Poll channels listed in registry (needs DISCORD_BOT_TOKEN)
  python scripts/kol_discord_ingest.py poll --limit 30

  # Rebuild consensus from stored signals
  python scripts/kol_discord_ingest.py consensus
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quantflow.strategy.kol_signals.aggregator import aggregate_consensus  # noqa: E402
from quantflow.strategy.kol_signals.discord_ingest import (  # noqa: E402
    ingest_channel_poll,
    ingest_export_file,
)
from quantflow.strategy.kol_signals.registry import load_kol_registry  # noqa: E402
from quantflow.strategy.kol_signals.store import KolSignalStore  # noqa: E402


def _cmd_export(args: argparse.Namespace) -> int:
    store = KolSignalStore(args.data_dir)
    result = ingest_export_file(
        args.path,
        registry_path=args.registry,
        store=store,
        process_images=args.images,
        ocr_backend=args.ocr,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _cmd_poll(args: argparse.Namespace) -> int:
    sources = load_kol_registry(args.registry)
    channels: list[str] = []
    if args.channel:
        channels = [args.channel]
    else:
        for s in sources:
            if s.enabled and s.platform == "discord":
                channels.extend(s.channel_ids)
    if not channels:
        print(
            "No channels: pass --channel ID or enable sources with channel_ids "
            "in quantflow/config/kol_registry.yaml",
            file=sys.stderr,
        )
        return 2
    store = KolSignalStore(args.data_dir)
    results = []
    for ch in channels:
        try:
            r = ingest_channel_poll(
                ch,
                registry_path=args.registry,
                store=store,
                limit=args.limit,
                process_images=args.images,
                ocr_backend=args.ocr,
            )
            results.append(r)
            print(f"[poll] channel={ch} ingested={r['ingested']} skipped={r['skipped']}")
        except Exception as exc:
            print(f"[poll] channel={ch} ERROR {exc}", file=sys.stderr)
            results.append({"channel_id": ch, "error": str(exc)})
    print(json.dumps({"results": results}, indent=2, ensure_ascii=False))
    return 0


def _cmd_consensus(args: argparse.Namespace) -> int:
    store = KolSignalStore(args.data_dir)
    signals = store.load_signals()
    window_ms = int(args.window_hours * 3600 * 1000)
    reports = aggregate_consensus(
        signals,
        window_ms=window_ms,
        min_sources=args.min_sources,
        min_score=args.min_score,
        min_confidence=args.min_confidence,
    )
    payload = [r.to_dict() for r in reports]
    store.append_consensus(payload)
    out = {
        "n_signals": len(signals),
        "n_reports": len(reports),
        "actionable": [r for r in payload if r.get("actionable")],
        "all": payload,
    }
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(
            json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"written {args.out}")
    print(json.dumps(out, indent=2, ensure_ascii=False)[:4000])
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--registry",
        default="quantflow/config/kol_registry.yaml",
        help="KOL registry YAML",
    )
    ap.add_argument(
        "--data-dir",
        default="data/kol_signals",
        help="JSONL store directory",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_exp = sub.add_parser("export", help="Ingest Discord export JSON")
    p_exp.add_argument("path", help="Export JSON path")
    p_exp.add_argument(
        "--images",
        action="store_true",
        help="Download/process image attachments + OCR",
    )
    p_exp.add_argument(
        "--ocr",
        default="none",
        choices=["none", "auto", "tesseract", "vision_stub"],
    )
    p_exp.set_defaults(func=_cmd_export)

    p_poll = sub.add_parser("poll", help="Poll Discord channels (bot token)")
    p_poll.add_argument("--channel", default="", help="Single channel id")
    p_poll.add_argument("--limit", type=int, default=50)
    p_poll.add_argument("--images", action="store_true", default=True)
    p_poll.add_argument("--no-images", action="store_false", dest="images")
    p_poll.add_argument(
        "--ocr",
        default="auto",
        choices=["none", "auto", "tesseract", "vision_stub"],
    )
    p_poll.set_defaults(func=_cmd_poll)

    p_con = sub.add_parser("consensus", help="Aggregate stored signals")
    p_con.add_argument("--window-hours", type=float, default=6.0)
    p_con.add_argument("--min-sources", type=int, default=2)
    p_con.add_argument("--min-score", type=float, default=0.35)
    p_con.add_argument("--min-confidence", type=float, default=0.35)
    p_con.add_argument(
        "--out",
        default="data/kol_signals/latest_consensus.json",
    )
    p_con.set_defaults(func=_cmd_consensus)

    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
