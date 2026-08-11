"""Discord message ingest for KOL channels.

Two modes:
1. **export JSON** — offline import of DiscordChatExporter / bot dumps
2. **bot poll** (optional) — REST history fetch with DISCORD_BOT_TOKEN

Never auto-executes trades. Outputs KolSignal records for consensus + audit.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from quantflow.strategy.kol_signals.chart_ocr import (
    enrich_text_with_ocr,
    process_attachment,
)
from quantflow.strategy.kol_signals.models import AttachmentMeta, KolSignal, SignalSide
from quantflow.strategy.kol_signals.parser import parse_trade_text
from quantflow.strategy.kol_signals.registry import (
    load_kol_registry,
    source_by_channel,
)
from quantflow.strategy.kol_signals.store import KolSignalStore

logger = logging.getLogger(__name__)


def _ms_from_discord_snowflake(message_id: str) -> int:
    """Discord snowflake → approx Unix ms."""
    try:
        return (int(message_id) >> 22) + 1_420_070_400_000
    except (TypeError, ValueError):
        return int(time.time() * 1000)


def _signal_id(platform: str, channel_id: str, message_id: str) -> str:
    raw = f"{platform}:{channel_id}:{message_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def message_to_signal(
    msg: dict[str, Any],
    *,
    source_id: str,
    weight: float = 1.0,
    platform: str = "discord",
    channel_id: str = "",
    process_images: bool = True,
    ocr_backend: str = "auto",
    attach_dir: str | Path = "data/kol_signals/attachments",
) -> KolSignal:
    """Convert a Discord-like message dict to KolSignal."""
    mid = str(msg.get("id") or msg.get("message_id") or "")
    ch = str(channel_id or msg.get("channel_id") or "")
    author_obj = msg.get("author") or {}
    if isinstance(author_obj, dict):
        author = str(
            author_obj.get("username")
            or author_obj.get("name")
            or author_obj.get("global_name")
            or ""
        )
    else:
        author = str(author_obj)
    text = str(msg.get("content") or msg.get("text") or "")
    ts = msg.get("timestamp_ms")
    if ts is None:
        # ISO timestamp or snowflake
        iso = msg.get("timestamp") or msg.get("created_at")
        if isinstance(iso, str) and iso:
            try:
                from datetime import datetime

                dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                ts = int(dt.timestamp() * 1000)
            except ValueError:
                ts = _ms_from_discord_snowflake(mid) if mid else int(time.time() * 1000)
        else:
            ts = _ms_from_discord_snowflake(mid) if mid else int(time.time() * 1000)

    attachments: list[AttachmentMeta] = []
    raw_atts = msg.get("attachments") or []
    if process_images and isinstance(raw_atts, list):
        for a in raw_atts:
            if not isinstance(a, dict):
                continue
            url = str(a.get("url") or a.get("proxy_url") or "")
            fname = str(a.get("filename") or a.get("name") or "")
            ctype = str(a.get("content_type") or a.get("contentType") or "")
            # Prefer local path if export already saved media
            local = str(a.get("local_path") or a.get("path") or "")
            meta = process_attachment(
                url=url,
                local_path=local,
                content_type=ctype,
                filename=fname,
                dest_dir=attach_dir,
                ocr_backend=ocr_backend,
                download=bool(url) and not local,
            )
            attachments.append(meta)

    parsed = parse_trade_text(text)
    if attachments:
        enriched = enrich_text_with_ocr(text, attachments)
        # Prefer OCR-enriched if it found more structure
        if enriched.get("confidence", 0) >= parsed.get("confidence", 0):
            parsed = enriched
            if enriched.get("ocr_used"):
                parsed.setdefault("parse_notes", []).append("ocr_merged")

    side = parsed["side"]
    if not isinstance(side, SignalSide):
        try:
            side = SignalSide(str(side))
        except ValueError:
            side = SignalSide.UNKNOWN

    return KolSignal(
        signal_id=_signal_id(platform, ch, mid or str(ts)),
        source_id=source_id,
        platform=platform,
        channel_id=ch,
        message_id=mid,
        author=author,
        created_at_ms=int(ts),
        raw_text=text,
        side=side,
        symbol=str(parsed.get("symbol") or ""),
        entry=parsed.get("entry"),
        stop_loss=parsed.get("stop_loss"),
        take_profit=list(parsed.get("take_profit") or []),
        timeframe=str(parsed.get("timeframe") or ""),
        confidence=float(parsed.get("confidence") or 0.0),
        weight=float(weight),
        attachments=attachments,
        parse_notes=list(parsed.get("parse_notes") or []),
        meta={"author": author},
    )


def ingest_export_file(
    path: str | Path,
    *,
    registry_path: str | Path | None = None,
    store: KolSignalStore | None = None,
    default_source_id: str = "discord_export",
    process_images: bool = False,
    ocr_backend: str = "none",
) -> dict[str, Any]:
    """Ingest a Discord export JSON (list of messages or {messages: [...]})."""
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        messages = data.get("messages") or data.get("msgs") or []
        channel_id = str(data.get("channel", {}).get("id") or data.get("channel_id") or "")
    elif isinstance(data, list):
        messages = data
        channel_id = ""
    else:
        return {"ingested": 0, "skipped": 0, "error": "unsupported_export_shape"}

    sources = load_kol_registry(registry_path)
    store = store or KolSignalStore()
    known = store.known_message_ids()
    ingested = 0
    skipped = 0
    signals: list[KolSignal] = []

    for msg in messages:
        if not isinstance(msg, dict):
            skipped += 1
            continue
        ch = str(msg.get("channel_id") or channel_id or "")
        mid = str(msg.get("id") or msg.get("message_id") or "")
        key = store.dedupe_key("discord", ch, mid)
        if mid and key in known:
            skipped += 1
            continue
        src = source_by_channel(sources, ch) if ch else None
        source_id = src.source_id if src else default_source_id
        weight = src.weight if src else 1.0
        sig = message_to_signal(
            msg,
            source_id=source_id,
            weight=weight,
            channel_id=ch,
            process_images=process_images,
            ocr_backend=ocr_backend,
        )
        signals.append(sig)
        known.add(key)
        ingested += 1

    store.append_signals(signals)
    return {
        "ingested": ingested,
        "skipped": skipped,
        "path": str(p),
        "signals": [s.to_dict() for s in signals[:5]],  # sample
        "n_signals_total_sample": len(signals),
    }


def fetch_channel_history(
    channel_id: str,
    *,
    token: str | None = None,
    limit: int = 50,
    before: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch recent messages via Discord REST API.

    Requires env DISCORD_BOT_TOKEN (or token=). Bot must be in the guild
    with Read Message History. No privileged intent required for REST history
    of channels the bot can see.
    """
    tok = token or os.environ.get("DISCORD_BOT_TOKEN", "")
    if not tok:
        raise RuntimeError("DISCORD_BOT_TOKEN not set")
    import urllib.error
    import urllib.parse
    import urllib.request

    q = urllib.parse.urlencode({"limit": max(1, min(int(limit), 100))})
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages?{q}"
    if before:
        url += f"&before={before}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bot {tok}",
            "User-Agent": "QuantFlow-KOL-Ingest/0.1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord API {exc.code}: {body[:300]}") from exc
    if not isinstance(payload, list):
        return []
    # attach channel_id for downstream
    for m in payload:
        if isinstance(m, dict) and "channel_id" not in m:
            m["channel_id"] = channel_id
    return payload


def ingest_channel_poll(
    channel_id: str,
    *,
    registry_path: str | Path | None = None,
    store: KolSignalStore | None = None,
    limit: int = 50,
    process_images: bool = True,
    ocr_backend: str = "auto",
    token: str | None = None,
) -> dict[str, Any]:
    """Poll one channel and append new signals."""
    messages = fetch_channel_history(channel_id, token=token, limit=limit)
    sources = load_kol_registry(registry_path)
    src = source_by_channel(sources, channel_id)
    source_id = src.source_id if src else f"discord:{channel_id}"
    weight = src.weight if src else 1.0
    store = store or KolSignalStore()
    known = store.known_message_ids()
    signals: list[KolSignal] = []
    skipped = 0
    for msg in messages:
        mid = str(msg.get("id") or "")
        key = store.dedupe_key("discord", channel_id, mid)
        if mid and key in known:
            skipped += 1
            continue
        sig = message_to_signal(
            msg,
            source_id=source_id,
            weight=weight,
            channel_id=channel_id,
            process_images=process_images,
            ocr_backend=ocr_backend,
        )
        signals.append(sig)
        known.add(key)
    store.append_signals(signals)
    return {
        "channel_id": channel_id,
        "ingested": len(signals),
        "skipped": skipped,
        "source_id": source_id,
    }
